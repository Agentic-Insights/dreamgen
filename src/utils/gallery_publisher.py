"""Publish approved DreamGen gallery assets to Cloudflare R2."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.utils.publication_catalog import (
    IMAGE_EXTENSIONS,
    PUBLIC_GALLERY_STATES,
    catalog_path_for,
    load_catalog,
)

DEFAULT_BUCKET = "dreamgen-gallery"


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

    entries = sorted(
        catalog["assets"].values(),
        key=lambda entry: str(entry.get("created_at", "")),
        reverse=True,
    )

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
        if entry.get("quality_flags"):
            skipped.append(SkippedAsset(key, f"quality_flags={','.join(entry['quality_flags'])}"))
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

        included_images += 1
        if limit is not None and included_images >= limit:
            break

    return PublishPlan(assets=assets, skipped=skipped, image_count=included_images, delete_count=0)


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

    result = subprocess.run(args, check=False, text=True, env=env)
    if result.returncode != 0:
        raise SystemExit(
            "Wrangler R2 command failed.\n"
            f"Bucket: {bucket}\n"
            f"Key: {key}\n"
            "Confirm CLOUDFLARE_R2_API_TOKEN has Workers R2 Storage Write or "
            "Workers R2 Storage Bucket Item Write for this bucket, then rerun."
        )


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


def delete_object(package: str, bucket: str, key: str, remote: bool) -> None:
    args = [*wrangler_base_args(package), "delete", f"{bucket}/{key}"]
    if remote:
        args.append("--remote")
    run_wrangler(args, bucket=bucket, key=key)


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


def validate_remote_environment(remote: bool) -> None:
    if not remote:
        return
    if not (os.getenv("CLOUDFLARE_R2_API_TOKEN") or os.getenv("CLOUDFLARE_API_TOKEN")):
        raise SystemExit(
            "CLOUDFLARE_R2_API_TOKEN or CLOUDFLARE_API_TOKEN is required "
            "for remote R2 publishing."
        )
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

    if not execute:
        return plan

    validate_remote_environment(remote)
    if smoke:
        smoke_test(wrangler_package, bucket, remote)
        if smoke_only:
            return plan

    for asset in plan.assets:
        put_object(wrangler_package, bucket, asset, remote)

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
    )
