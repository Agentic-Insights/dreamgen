"""Publish approved DreamGen gallery assets to Cloudflare R2."""

from src.utils.gallery_publisher import discover_assets, main

if __name__ == "__main__":
    main()
