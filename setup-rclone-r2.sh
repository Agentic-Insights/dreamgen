#!/bin/bash
# Setup rclone for Cloudflare R2
# This creates an rclone config for the dreamgen-gallery bucket

set -e

echo "=== Cloudflare R2 rclone Setup ==="
echo
echo "You need:"
echo "  1. R2 Access Key ID"
echo "  2. R2 Secret Access Key"
echo "  3. Account ID (default: f5abe6cf148f6acb358556290377dc12)"
echo
echo "Get these from: https://dash.cloudflare.com → R2 → Manage R2 API Tokens"
echo

# Check if config already exists
if rclone listremotes | grep -q "^r2:$"; then
    echo "⚠️  R2 remote already configured!"
    read -p "Reconfigure? (y/n): " reconfigure
    if [ "$reconfigure" != "y" ]; then
        echo "Cancelled"
        exit 0
    fi
fi

# Get credentials
read -p "R2 Access Key ID: " access_key
read -sp "R2 Secret Access Key: " secret_key
echo
read -p "Account ID [f5abe6cf148f6acb358556290377dc12]: " account_id
account_id=${account_id:-f5abe6cf148f6acb358556290377dc12}

# Create rclone config
rclone config create r2 s3 \
    provider=Cloudflare \
    access_key_id="$access_key" \
    secret_access_key="$secret_key" \
    endpoint="https://$account_id.r2.cloudflarestorage.com" \
    acl=private

echo
echo "✓ rclone configured for R2!"
echo
echo "Test it:"
echo "  just r2-list          # List bucket contents"
echo "  just sync-dry         # See what would sync (dry run)"
echo "  just sync             # Actually sync (deletes remote files not in local)"
echo "  just sync-copy        # Copy only (no deletes)"
echo
