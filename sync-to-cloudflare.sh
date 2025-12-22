#!/bin/bash
# Sync DreamGen images to Cloudflare R2
# Usage: ./sync-to-cloudflare.sh [--all]
#   --all: Upload all images (default: only images from last hour)

set -e

BUCKET="dreamgen-gallery"
OUTPUT_DIR="/home/vaskin/projects/dreamgen/output"
ACCOUNT_ID="f5abe6cf148f6acb358556290377dc12"

export CLOUDFLARE_ACCOUNT_ID=$ACCOUNT_ID

if [ "$1" = "--all" ]; then
    echo "Uploading all images..."
    FIND_ARGS=""
else
    echo "Uploading images from last hour..."
    FIND_ARGS="-mmin -60"
fi

count=0
find "$OUTPUT_DIR" -name "*.png" -size +10k $FIND_ARGS 2>/dev/null | while read img; do
    filename=$(basename "$img")
    echo "Uploading $filename..."
    wrangler r2 object put "$BUCKET/$filename" --file "$img" --remote 2>/dev/null
    ((count++)) || true
done

echo "Done! Uploaded images to R2."
echo "View gallery at: https://dreamgen.agenticinsights.com"
echo "Or: https://dreamgen-gallery.pages.dev"
