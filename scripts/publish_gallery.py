"""Publish approved DreamGen gallery assets to Cloudflare R2.

This is intentionally conservative: dry-run is the default, mock placeholders
are skipped from metadata, and remote deletion/pruning is not implemented here.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_BUCKET = "dreamgen-gallery"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@dataclass(frozen=True)
class PublishAsset:
    path: Path
    key: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish non-placeholder DreamGen gallery assets to Cloudflare R2."
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
        "--execute",
        action="store_true",
        help="Upload files. Without this flag the command only prints a dry-run plan.",
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


def read_metadata(image_path: Path) -> dict:
    metadata_path = image_path.with_suffix(".meta.json")
    if not metadata_path.exists():
        return {}

    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def is_placeholder(image_path: Path) -> bool:
    metadata = read_metadata(image_path)
    return bool(metadata.get("is_placeholder")) or metadata.get("backend") == "mock"


def parse_since(value: str | None) -> float | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").timestamp()


def object_key(path: Path, output_dir: Path) -> str:
    return path.relative_to(output_dir).as_posix()


def discover_assets(output_dir: Path, since: float | None, limit: int | None) -> list[PublishAsset]:
    if not output_dir.exists():
        raise SystemExit(f"Output directory does not exist: {output_dir}")

    assets: list[PublishAsset] = []
    images = sorted(
        (
            path
            for path in output_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    included_images = 0
    for image_path in images:
        if since and image_path.stat().st_mtime < since:
            continue
        if is_placeholder(image_path):
            continue

        assets.append(PublishAsset(image_path, object_key(image_path, output_dir)))
        included_images += 1
        prompt_path = image_path.with_suffix(".txt")
        if prompt_path.exists():
            assets.append(PublishAsset(prompt_path, object_key(prompt_path, output_dir)))

        if limit is not None and included_images >= limit:
            break

    return assets


def wrangler_base_args(package: str) -> list[str]:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise SystemExit("npx is required to run Wrangler R2 commands.")
    return [npx, package, "r2", "object"]


def run_wrangler(args: list[str]) -> None:
    env = os.environ.copy()
    r2_token = env.get("CLOUDFLARE_R2_API_TOKEN")
    if r2_token:
        env["CLOUDFLARE_API_TOKEN"] = r2_token

    result = subprocess.run(args, check=False, text=True, env=env)
    if result.returncode != 0:
        raise SystemExit(
            "Wrangler R2 command failed. Confirm CLOUDFLARE_R2_API_TOKEN has "
            "Workers R2 Storage Write or Workers R2 Storage Bucket Item Write "
            "for dreamgen-gallery, then rerun the command."
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
    run_wrangler(args)


def delete_object(package: str, bucket: str, key: str, remote: bool) -> None:
    args = [*wrangler_base_args(package), "delete", f"{bucket}/{key}"]
    if remote:
        args.append("--remote")
    run_wrangler(args)


def smoke_test(package: str, bucket: str, remote: bool) -> None:
    key = f".smoke/publish-validation-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.txt"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
        file.write("dreamgen publish smoke test\n")
        smoke_path = Path(file.name)

    try:
        put_object(package, bucket, PublishAsset(smoke_path, key), remote)
        delete_object(package, bucket, key, remote)
    finally:
        try:
            smoke_path.unlink()
        except OSError:
            pass


def main() -> None:
    args = parse_args()
    since = parse_since(args.since)
    remote = not args.local
    assets = discover_assets(args.output_dir, since, args.limit)

    image_count = len([asset for asset in assets if asset.path.suffix.lower() in IMAGE_EXTENSIONS])
    print(f"bucket={args.bucket}")
    print(f"target={'remote' if remote else 'local'}")
    print(f"images={image_count}")
    print(f"files={len(assets)}")

    if not args.execute:
        for asset in assets[:20]:
            print(f"DRY-RUN {asset.key}")
        if len(assets) > 20:
            print(f"DRY-RUN ... {len(assets) - 20} more files")
        print("Add --execute to upload.")
        return

    if remote and not (os.getenv("CLOUDFLARE_R2_API_TOKEN") or os.getenv("CLOUDFLARE_API_TOKEN")):
        raise SystemExit(
            "CLOUDFLARE_R2_API_TOKEN or CLOUDFLARE_API_TOKEN is required "
            "for remote R2 publishing."
        )
    if remote and not os.getenv("CLOUDFLARE_ACCOUNT_ID"):
        raise SystemExit("CLOUDFLARE_ACCOUNT_ID is required for remote R2 publishing.")

    if args.smoke_test:
        smoke_test(args.wrangler_package, args.bucket, remote)
        if args.smoke_test_only:
            return

    for asset in assets:
        print(f"UPLOAD {asset.key}")
        put_object(args.wrangler_package, args.bucket, asset, remote)


if __name__ == "__main__":
    main()
