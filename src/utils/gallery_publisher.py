"""Publish approved DreamGen gallery assets to Cloudflare R2."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.publication_catalog import (
    IMAGE_EXTENSIONS,
    PUBLIC_GALLERY_STATES,
    PUBLICATION_BLOCKING_QUALITY_FLAGS,
    catalog_path_for,
    load_catalog,
)

DEFAULT_BUCKET = "dreamgen-gallery"
CURRENT_MANIFEST_KEY = "_dreamgen/current.json"
RELEASE_MANIFEST_PREFIX = "_dreamgen/releases"
MANIFEST_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class PublishAsset:
    """A local file and destination R2 object key."""

    path: Path
    key: str
    reason: str


@dataclass(frozen=True)
class SkippedAsset:
    """A catalog asset skipped by the publisher."""

    key: str
    reason: str


@dataclass(frozen=True)
class PublishPlan:
    """Dry-run or execution plan for gallery publishing."""

    assets: list[PublishAsset]
    skipped: list[SkippedAsset]
    image_count: int
    delete_count: int = 0

    @property
    def file_count(self) -> int:
        return len(self.assets)


@dataclass(frozen=True)
class PublishRelease:
    """An ordered, rollback-linked public gallery release."""

    manifest: dict[str, Any]
    current_key: str = CURRENT_MANIFEST_KEY

    @property
    def release_id(self) -> str:
        return str(self.manifest["release_id"])

    @property
    def release_key(self) -> str:
        return f"{RELEASE_MANIFEST_PREFIX}/{self.release_id}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish approved DreamGen gallery assets to Cloudflare R2."
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--since",
        default=None,
        help="Only include files modified on or after YYYY-MM-DD.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the publish plan without uploading. This is the default.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Upload files. Without this flag the command only prints a dry-run plan.",
    )
    parser.add_argument(
        "--include-featured",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include featured assets along with published assets.",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Reserved for future remote deletions. No objects are deleted without this flag.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Upload and delete a tiny smoke-test object before publishing.",
    )
    parser.add_argument(
        "--smoke-test-only",
        action="store_true",
        help="Only run the smoke test; do not publish gallery assets afterward.",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use Wrangler's local R2 simulation instead of remote Cloudflare R2.",
    )
    parser.add_argument(
        "--wrangler-package",
        default="wrangler@4",
        help="Package passed to npx, for example wrangler@4.",
    )
    parser.add_argument(
        "--transport",
        choices=("auto", "rclone", "wrangler"),
        default="auto",
        help="Upload transport. Auto prefers rclone and falls back to Wrangler.",
    )
    parser.add_argument(
        "--rclone-remote",
        default="r2",
        help="Configured rclone remote name used by the rclone transport.",
    )
    parser.add_argument(
        "--transfers",
        type=int,
        default=8,
        help="Parallel file transfers used by rclone.",
    )
    return parser.parse_args()


def parse_since(value: str | None) -> float | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").timestamp()


def object_key(path: Path, output_dir: Path) -> str:
    return path.relative_to(output_dir).as_posix()


def _approved_states(include_featured: bool) -> set[str]:
    states = set(PUBLIC_GALLERY_STATES)
    if not include_featured:
        states.discard("featured")
    return states


def _add_sidecar(
    assets: list[PublishAsset], sidecar_path: Path, output_dir: Path, reason: str
) -> None:
    if sidecar_path.exists():
        assets.append(PublishAsset(sidecar_path, object_key(sidecar_path, output_dir), reason))


def _entry_sort_key(entry: dict[str, Any]) -> tuple[str, str]:
    """Return a stable newest-first ordering key with a path tie-breaker."""
    return (str(entry.get("created_at", "")), str(entry.get("path", "")))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_publish_plan(
    output_dir: Path,
    since: float | None,
    limit: int | None,
    *,
    include_featured: bool = True,
    prune: bool = False,
) -> PublishPlan:
    """Build a catalog-driven R2 publish plan."""
    if not output_dir.exists():
        raise SystemExit(f"Output directory does not exist: {output_dir}")
    if not catalog_path_for(output_dir).exists():
        raise SystemExit(
            "Publication catalog is missing. Backfill or generate through the backend first: "
            "POST /api/gallery/catalog/backfill"
        )

    catalog = load_catalog(output_dir)
    approved_states = _approved_states(include_featured)
    assets: list[PublishAsset] = []
    skipped: list[SkippedAsset] = []
    included_images = 0

    entries = sorted(catalog["assets"].values(), key=_entry_sort_key, reverse=True)

    for entry in entries:
        key = str(entry.get("path", ""))
        state = str(entry.get("publication_state", "draft"))
        image_path = output_dir / key

        if state not in approved_states:
            skipped.append(SkippedAsset(key, f"state={state}"))
            continue
        if not bool(entry.get("publishable", True)):
            skipped.append(SkippedAsset(key, "not publishable"))
            continue
        metadata = entry.get("metadata") or {}
        lineage = metadata.get("edit_lineage") if isinstance(metadata, dict) else None
        if isinstance(lineage, dict) and (
            lineage.get("role") != "derivative" or lineage.get("decision_state") != "approved"
        ):
            skipped.append(SkippedAsset(key, "edit derivative is not explicitly approved"))
            continue
        decision_manifest_path = None
        if isinstance(lineage, dict):
            manifest_key = str(lineage.get("decision_manifest_path") or "")
            expected_sha = str(lineage.get("decision_manifest_sha256") or "")
            candidate = (output_dir / manifest_key).resolve()
            try:
                candidate.relative_to(output_dir.resolve())
            except ValueError:
                skipped.append(SkippedAsset(key, "edit decision manifest is outside output"))
                continue
            if not manifest_key or not expected_sha or not candidate.is_file():
                skipped.append(SkippedAsset(key, "edit decision manifest is missing"))
                continue
            if _sha256(candidate) != expected_sha:
                skipped.append(SkippedAsset(key, "edit decision manifest hash mismatch"))
                continue
            decision_manifest_path = candidate
        quality_flags = {str(flag) for flag in entry.get("quality_flags", [])}
        blocking_flags = sorted(quality_flags & PUBLICATION_BLOCKING_QUALITY_FLAGS)
        if blocking_flags:
            skipped.append(SkippedAsset(key, f"quality_flags={','.join(blocking_flags)}"))
            continue
        if image_path.suffix.lower() not in IMAGE_EXTENSIONS or not image_path.exists():
            skipped.append(SkippedAsset(key, "missing image file"))
            continue
        if since and image_path.stat().st_mtime < since:
            skipped.append(SkippedAsset(key, "older than --since"))
            continue

        reason = f"state={state}"
        assets.append(PublishAsset(image_path, object_key(image_path, output_dir), reason))
        _add_sidecar(assets, image_path.with_suffix(".txt"), output_dir, "prompt sidecar")
        _add_sidecar(assets, image_path.with_suffix(".meta.json"), output_dir, "metadata sidecar")
        if decision_manifest_path:
            _add_sidecar(
                assets,
                decision_manifest_path,
                output_dir,
                "immutable edit decision manifest",
            )

        included_images += 1
        if limit is not None and included_images >= limit:
            break

    return PublishPlan(assets=assets, skipped=skipped, image_count=included_images, delete_count=0)


def build_release_manifest(
    output_dir: Path,
    plan: PublishPlan,
    *,
    published_at: str | None = None,
    previous_release: dict[str, Any] | None = None,
) -> PublishRelease:
    """Build the exact ordered public view represented by a publish plan."""
    catalog = load_catalog(output_dir)
    entries = catalog["assets"]
    image_assets = [asset for asset in plan.assets if asset.path.suffix.lower() in IMAGE_EXTENSIONS]
    items: list[dict[str, Any]] = []

    for position, asset in enumerate(image_assets):
        entry = entries.get(asset.key)
        if not isinstance(entry, dict):
            raise SystemExit(f"Catalog entry disappeared while building release: {asset.key}")
        digest = _sha256(asset.path)
        caption_path = asset.path.with_suffix(".txt")
        metadata_path = asset.path.with_suffix(".meta.json")
        caption_version = _sha256(caption_path)[:20] if caption_path.exists() else None
        metadata_version = _sha256(metadata_path)[:20] if metadata_path.exists() else None
        state = str(entry.get("publication_state", "published"))
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata = {
            **metadata,
            "publication": {
                "state": state,
                "approved_at": entry.get("published_at") or entry.get("updated_at"),
            },
        }
        edit_lineage = metadata.get("edit_lineage")
        decision_manifest_path = None
        decision_manifest_sha = None
        if isinstance(edit_lineage, dict) and edit_lineage.get("decision_manifest_path"):
            decision_manifest_path = output_dir / str(edit_lineage["decision_manifest_path"])
            decision_manifest_sha = _sha256(decision_manifest_path)
        items.append(
            {
                "position": position,
                "key": asset.key,
                "asset_version": digest[:20],
                "sha256": digest,
                "size": asset.path.stat().st_size,
                "created_at": entry.get("created_at"),
                "approved_at": entry.get("published_at") or entry.get("updated_at"),
                "publication_state": state,
                "featured": state == "featured",
                "caption_key": (
                    object_key(caption_path, output_dir) if caption_path.exists() else None
                ),
                "caption_version": caption_version,
                "metadata_key": (
                    object_key(metadata_path, output_dir) if metadata_path.exists() else None
                ),
                "metadata_version": metadata_version,
                "metadata": metadata,
                "edit_lineage": edit_lineage if isinstance(edit_lineage, dict) else None,
                "decision_manifest_key": (
                    object_key(decision_manifest_path, output_dir)
                    if decision_manifest_path
                    else None
                ),
                "decision_manifest_version": (
                    decision_manifest_sha[:20] if decision_manifest_sha else None
                ),
                "decision_manifest_sha256": decision_manifest_sha,
            }
        )

    release_time = published_at or utc_now()
    previous_id = None
    previous_key = None
    if isinstance(previous_release, dict):
        previous_id = previous_release.get("release_id")
        previous_key = previous_release.get("release_key")
        if not previous_key and previous_id:
            previous_key = f"{RELEASE_MANIFEST_PREFIX}/{previous_id}.json"

    source_catalog = {
        "version": catalog.get("version"),
        "updated_at": catalog.get("updated_at"),
        "sha256": _sha256(catalog_path_for(output_dir)),
    }
    identity = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "published_at": release_time,
        "source_catalog": source_catalog,
        "items": [
            {
                "position": item["position"],
                "key": item["key"],
                "asset_version": item["asset_version"],
                "caption_version": item["caption_version"],
                "metadata_version": item["metadata_version"],
                "publication_state": item["publication_state"],
                "created_at": item["created_at"],
                "approved_at": item["approved_at"],
                "edit_lineage": item["edit_lineage"],
                "decision_manifest_key": item["decision_manifest_key"],
                "decision_manifest_version": item["decision_manifest_version"],
            }
            for item in items
        ],
    }
    release_id = f"{release_time[:10].replace('-', '')}-{_json_hash(identity)[:16]}"
    release_key = f"{RELEASE_MANIFEST_PREFIX}/{release_id}.json"
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "release_id": release_id,
        "release_key": release_key,
        "published_at": release_time,
        "image_count": len(items),
        "leading_key": items[0]["key"] if items else None,
        "source_catalog": source_catalog,
        "rollback": {
            "previous_release_id": previous_id,
            "previous_release_key": previous_key,
        },
        "items": items,
    }
    return PublishRelease(manifest=manifest)


def build_publish_status(
    output_dir: Path,
    *,
    bucket: str = DEFAULT_BUCKET,
    since: str | None = None,
    limit: int | None = None,
    include_featured: bool = True,
    prune: bool = False,
    preview_limit: int = 10,
) -> dict[str, object]:
    """Return a non-mutating local status snapshot for the R2 publish workflow."""
    approved_states = sorted(_approved_states(include_featured))
    command = "uv run dreamgen publish --execute"
    if bucket != DEFAULT_BUCKET:
        command += f" --bucket {bucket}"
    if since:
        command += f" --since {since}"
    if limit is not None:
        command += f" --limit {limit}"
    if not include_featured:
        command += " --no-include-featured"
    if prune:
        command += " --prune"

    status: dict[str, object] = {
        "bucket": bucket,
        "approved_states": approved_states,
        "catalog_present": catalog_path_for(output_dir).exists(),
        "output_present": output_dir.exists(),
        "ready": False,
        "needs_publish": False,
        "upload_images": 0,
        "upload_files": 0,
        "skipped_assets": 0,
        "delete_objects": 0,
        "preview_assets": [],
        "skipped_preview": [],
        "command": command,
        "message": "",
    }

    if not output_dir.exists():
        status["message"] = f"Output directory does not exist: {output_dir}"
        return status
    if not catalog_path_for(output_dir).exists():
        status["message"] = (
            "Publication catalog is missing. Backfill or generate through the backend first."
        )
        return status

    plan = build_publish_plan(
        output_dir,
        parse_since(since),
        limit,
        include_featured=include_featured,
        prune=prune,
    )

    status.update(
        {
            "ready": True,
            "needs_publish": plan.file_count > 0 or (prune and plan.delete_count > 0),
            "upload_images": plan.image_count,
            "upload_files": plan.file_count,
            "skipped_assets": len(plan.skipped),
            "delete_objects": plan.delete_count if prune else 0,
            "preview_assets": [
                {"key": asset.key, "reason": asset.reason} for asset in plan.assets[:preview_limit]
            ],
            "skipped_preview": [
                {"key": skipped.key, "reason": skipped.reason}
                for skipped in plan.skipped[:preview_limit]
            ],
            "message": (
                "Approved local assets are ready for R2 publishing."
                if plan.file_count
                else "No approved local assets are currently in the publish plan."
            ),
        }
    )
    return status


def discover_assets(output_dir: Path, since: float | None, limit: int | None) -> list[PublishAsset]:
    """Compatibility wrapper used by tests and older callers."""
    return build_publish_plan(output_dir, since, limit).assets


def wrangler_base_args(package: str) -> list[str]:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise SystemExit("npx is required to run Wrangler R2 commands.")
    return [npx, package, "r2", "object"]


def run_wrangler(args: list[str], *, bucket: str, key: str) -> None:
    env = os.environ.copy()
    r2_token = env.get("CLOUDFLARE_R2_API_TOKEN")
    if r2_token:
        env["CLOUDFLARE_API_TOKEN"] = r2_token

    result = subprocess.run(
        args,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        detail_line = detail[-1] if detail else "unknown Wrangler error"
        raise SystemExit(
            "Wrangler R2 command failed.\n"
            f"Bucket: {bucket}\n"
            f"Key: {key}\n"
            f"Detail: {detail_line}\n"
            "Confirm CLOUDFLARE_R2_API_TOKEN has Workers R2 Storage Write or "
            "Workers R2 Storage Bucket Item Write for this bucket, then rerun."
        )


def try_get_wrangler_object(
    package: str,
    bucket: str,
    key: str,
    destination: Path,
    remote: bool,
) -> bool:
    args = [*wrangler_base_args(package), "get", f"{bucket}/{key}", "--file", str(destination)]
    if remote:
        args.append("--remote")
    env = os.environ.copy()
    r2_token = env.get("CLOUDFLARE_R2_API_TOKEN")
    if r2_token:
        env["CLOUDFLARE_API_TOKEN"] = r2_token
    result = subprocess.run(args, check=False, text=True, capture_output=True, env=env)
    return result.returncode == 0 and destination.exists()


def put_object(package: str, bucket: str, asset: PublishAsset, remote: bool) -> None:
    args = [
        *wrangler_base_args(package),
        "put",
        f"{bucket}/{asset.key}",
        "--file",
        str(asset.path),
    ]
    if remote:
        args.append("--remote")
    run_wrangler(args, bucket=bucket, key=asset.key)


def wrangler_put_assets(
    plan: PublishPlan,
    *,
    package: str,
    bucket: str,
    remote: bool,
    transfers: int,
) -> None:
    """Upload the exact approved plan with bounded Wrangler concurrency."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, transfers)) as executor:
        futures = {
            executor.submit(put_object, package, bucket, asset, remote): asset
            for asset in plan.assets
        }
        for future in concurrent.futures.as_completed(futures):
            asset = futures[future]
            try:
                future.result()
            except BaseException as exc:
                for pending in futures:
                    pending.cancel()
                raise SystemExit(
                    "Wrangler gallery publishing failed. The release pointer was not updated.\n"
                    f"Bucket: {bucket}\n"
                    f"Key: {asset.key}"
                ) from exc


def delete_object(package: str, bucket: str, key: str, remote: bool) -> None:
    args = [*wrangler_base_args(package), "delete", f"{bucket}/{key}"]
    if remote:
        args.append("--remote")
    run_wrangler(args, bucket=bucket, key=key)


def resolve_transport(transport: str, *, remote: bool) -> str:
    if transport != "auto":
        if transport == "rclone" and not remote:
            raise SystemExit("The rclone transport is only available for remote publishing.")
        return transport
    if remote and shutil.which("rclone"):
        return "rclone"
    return "wrangler"


def rclone_target(remote_name: str, bucket: str, key: str | None = None) -> str:
    base = f"{remote_name.rstrip(':')}:{bucket}"
    return f"{base}/{key}" if key else base


def run_rclone(args: list[str], *, target: str) -> None:
    rclone = shutil.which("rclone")
    if not rclone:
        raise SystemExit("rclone is required for the selected publish transport.")
    result = subprocess.run([rclone, *args], check=False, text=True)
    if result.returncode != 0:
        raise SystemExit(f"rclone gallery publishing failed for {target}.")


def rclone_copy_assets(
    plan: PublishPlan,
    *,
    output_dir: Path,
    bucket: str,
    remote_name: str,
    transfers: int,
) -> None:
    """Copy exactly the approved plan without mirroring or deleting remote objects."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
        for asset in plan.assets:
            file.write(f"{asset.key}\n")
        files_from = Path(file.name)
    try:
        target = rclone_target(remote_name, bucket)
        run_rclone(
            [
                "copy",
                str(output_dir),
                target,
                "--files-from",
                str(files_from),
                "--no-traverse",
                "--transfers",
                str(max(1, transfers)),
                "--checkers",
                str(max(2, transfers * 2)),
            ],
            target=target,
        )
    finally:
        try:
            files_from.unlink()
        except OSError:
            pass


def rclone_put_object(path: Path, *, bucket: str, key: str, remote_name: str) -> None:
    target = rclone_target(remote_name, bucket, key)
    run_rclone(["copyto", str(path), target], target=target)


def try_get_rclone_object(*, bucket: str, key: str, destination: Path, remote_name: str) -> bool:
    rclone = shutil.which("rclone")
    if not rclone:
        return False
    target = rclone_target(remote_name, bucket, key)
    result = subprocess.run(
        [rclone, "copyto", target, str(destination)],
        check=False,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0 and destination.exists()


def load_previous_release(
    *,
    transport: str,
    package: str,
    bucket: str,
    remote: bool,
    remote_name: str,
    temp_dir: Path,
) -> dict[str, Any] | None:
    destination = temp_dir / "previous-current.json"
    if transport == "rclone":
        found = try_get_rclone_object(
            bucket=bucket,
            key=CURRENT_MANIFEST_KEY,
            destination=destination,
            remote_name=remote_name,
        )
    else:
        found = try_get_wrangler_object(
            package,
            bucket,
            CURRENT_MANIFEST_KEY,
            destination,
            remote,
        )
    if not found:
        return None
    try:
        payload = json.loads(destination.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def publish_release_manifests(
    release: PublishRelease,
    *,
    transport: str,
    package: str,
    bucket: str,
    remote: bool,
    remote_name: str,
    temp_dir: Path,
) -> None:
    """Publish the immutable release first and move the current pointer last."""
    release_path = temp_dir / "release.json"
    current_path = temp_dir / "current.json"
    payload = json.dumps(release.manifest, indent=2, sort_keys=True)
    release_path.write_text(payload, encoding="utf-8")
    current_path.write_text(payload, encoding="utf-8")

    for path, key in ((release_path, release.release_key), (current_path, release.current_key)):
        if transport == "rclone":
            rclone_put_object(path, bucket=bucket, key=key, remote_name=remote_name)
        else:
            put_object(package, bucket, PublishAsset(path, key, "release manifest"), remote)


def smoke_test(package: str, bucket: str, remote: bool) -> None:
    key = f".smoke/publish-validation-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.txt"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
        file.write("dreamgen publish smoke test\n")
        smoke_path = Path(file.name)

    try:
        put_object(package, bucket, PublishAsset(smoke_path, key, "smoke test"), remote)
        delete_object(package, bucket, key, remote)
    finally:
        try:
            smoke_path.unlink()
        except OSError:
            pass


def validate_remote_environment(remote: bool, transport: str) -> None:
    if not remote or transport == "rclone":
        return
    if not os.getenv("CLOUDFLARE_ACCOUNT_ID"):
        raise SystemExit("CLOUDFLARE_ACCOUNT_ID is required for remote R2 publishing.")


def print_plan(plan: PublishPlan, *, bucket: str, remote: bool, execute: bool, prune: bool) -> None:
    mode = "execute" if execute else "dry-run"
    print(f"bucket={bucket}")
    print(f"target={'remote' if remote else 'local'}")
    print(f"mode={mode}")
    print(f"upload_images={plan.image_count}")
    print(f"upload_files={plan.file_count}")
    print(f"skipped_assets={len(plan.skipped)}")
    print(f"delete_objects={plan.delete_count if prune else 0}")
    print(f"prune={'enabled' if prune else 'disabled'}")
    print(f"release_manifest={CURRENT_MANIFEST_KEY}")

    for asset in plan.assets[:50]:
        action = "UPLOAD" if execute else "DRY-RUN UPLOAD"
        print(f"{action} {asset.key} ({asset.reason})")
    if len(plan.assets) > 50:
        print(f"DRY-RUN ... {len(plan.assets) - 50} more upload files")
    for skipped_asset in plan.skipped[:20]:
        print(f"SKIP {skipped_asset.key} ({skipped_asset.reason})")
    if len(plan.skipped) > 20:
        print(f"SKIP ... {len(plan.skipped) - 20} more catalog assets")
    if not execute:
        print("Add --execute to upload.")


def publish_gallery(
    *,
    output_dir: Path,
    bucket: str = DEFAULT_BUCKET,
    since: str | None = None,
    limit: int | None = None,
    execute: bool = False,
    include_featured: bool = True,
    prune: bool = False,
    smoke: bool = False,
    smoke_only: bool = False,
    local: bool = False,
    wrangler_package: str = "wrangler@4",
    transport: str = "auto",
    rclone_remote: str = "r2",
    transfers: int = 8,
) -> PublishPlan:
    """Build and optionally execute the gallery publishing workflow."""
    since_timestamp = parse_since(since)
    remote = not local
    plan = build_publish_plan(
        output_dir,
        since_timestamp,
        limit,
        include_featured=include_featured,
        prune=prune,
    )
    print_plan(plan, bucket=bucket, remote=remote, execute=execute, prune=prune)
    selected_transport = resolve_transport(transport, remote=remote)
    print(f"transport={selected_transport}")

    if not execute:
        preview = build_release_manifest(output_dir, plan)
        print(f"release_id={preview.release_id}")
        print(f"release_images={preview.manifest['image_count']}")
        print(f"leading_key={preview.manifest['leading_key']}")
        return plan

    validate_remote_environment(remote, selected_transport)
    if smoke:
        smoke_test(wrangler_package, bucket, remote)
        if smoke_only:
            return plan

    with tempfile.TemporaryDirectory(prefix="dreamgen-gallery-release-") as temp_name:
        temp_dir = Path(temp_name)
        previous_release = load_previous_release(
            transport=selected_transport,
            package=wrangler_package,
            bucket=bucket,
            remote=remote,
            remote_name=rclone_remote,
            temp_dir=temp_dir,
        )

        if selected_transport == "rclone":
            try:
                rclone_copy_assets(
                    plan,
                    output_dir=output_dir,
                    bucket=bucket,
                    remote_name=rclone_remote,
                    transfers=transfers,
                )
            except SystemExit:
                if transport != "auto":
                    raise
                selected_transport = "wrangler"
                print("rclone_write_failed=fallback_to_wrangler")
                validate_remote_environment(remote, selected_transport)
                previous_release = load_previous_release(
                    transport=selected_transport,
                    package=wrangler_package,
                    bucket=bucket,
                    remote=remote,
                    remote_name=rclone_remote,
                    temp_dir=temp_dir,
                )
                wrangler_put_assets(
                    plan,
                    package=wrangler_package,
                    bucket=bucket,
                    remote=remote,
                    transfers=transfers,
                )
        else:
            wrangler_put_assets(
                plan,
                package=wrangler_package,
                bucket=bucket,
                remote=remote,
                transfers=transfers,
            )

        release = build_release_manifest(
            output_dir,
            plan,
            previous_release=previous_release,
        )
        publish_release_manifests(
            release,
            transport=selected_transport,
            package=wrangler_package,
            bucket=bucket,
            remote=remote,
            remote_name=rclone_remote,
            temp_dir=temp_dir,
        )
        print(f"release_id={release.release_id}")
        print(f"release_key={release.release_key}")
        print(f"leading_key={release.manifest['leading_key']}")
        print(
            "previous_release_id="
            f"{release.manifest['rollback']['previous_release_id'] or 'none'}"
        )

    return plan


def main() -> None:
    args = parse_args()
    publish_gallery(
        output_dir=args.output_dir,
        bucket=args.bucket,
        since=args.since,
        limit=args.limit,
        execute=args.execute and not args.dry_run,
        include_featured=args.include_featured,
        prune=args.prune,
        smoke=args.smoke_test,
        smoke_only=args.smoke_test_only,
        local=args.local,
        wrangler_package=args.wrangler_package,
        transport=args.transport,
        rclone_remote=args.rclone_remote,
        transfers=args.transfers,
    )
