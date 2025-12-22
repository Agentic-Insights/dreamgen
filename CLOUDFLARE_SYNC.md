# Cloudflare R2 Sync Setup

## Overview

DreamGen uses **two R2 buckets** for different purposes:

1. **`dreamgen-gallery`** - Full collection of all images (used by gallery Pages app)
2. **`continuous-image-gen`** - Latest image only (used by host-image Worker)

## Live URLs

- **Latest Image**: https://host-image.agentic.workers.dev/
- **Gallery**: https://dreamgen.agenticinsights.com / https://dreamgen-gallery.pages.dev

## Sync Commands

### Quick Reference

```bash
just sync              # Sync to BOTH buckets (recommended)
just sync-gallery      # Sync only full collection
just sync-latest       # Sync only latest image
just r2-list           # List contents of both buckets
```

### How It Works

**`just sync`** does two things:
1. Syncs entire `output/` directory to `dreamgen-gallery` (using rclone)
2. Uploads the most recent PNG to `continuous-image-gen` (using wrangler)

The sync is intelligent:
- **Gallery bucket**: True sync with rclone - deletes old files, mirrors local state
- **Latest bucket**: Wrangler upload - faster, uses your existing Cloudflare auth

### R2 API Token Setup

Your current R2 API token (`83b49ec3...`) is scoped to `dreamgen-gallery` only.

To enable rclone for both buckets:
1. Go to: https://dash.cloudflare.com → R2 → Manage R2 API Tokens
2. Create new token with "Admin Read & Write" permissions
3. **Important**: Don't scope to specific buckets (allow access to all)
4. Run: `just setup-rclone` and enter the new credentials

For now, the hybrid approach (rclone + wrangler) works perfectly!

## Worker Configuration

### host-image Worker
- **Binding**: `DREAM_BUCKET` → `continuous-image-gen`
- **Function**: Serves the latest generated image
- **Cache**: 5 minutes (to show updates faster)
- **Code**: Automatically finds and serves most recent PNG

### cloudflare-gallery Pages
- **Binding**: `GALLERY` → `dreamgen-gallery`
- **Function**: Full gallery with slideshow
- **API**: `/api/images` lists all, `/api/images/{key}` serves individual files

## Deployment Workflow

```bash
# Generate some images
just gen

# Sync to R2
just sync

# Deploy workers (if code changed)
just deploy-host        # Deploy host-image worker
just deploy-gallery     # Deploy gallery Pages app
just deploy             # Deploy both + sync
```

## Troubleshooting

### "Access Denied" errors
- Your R2 API token might be scoped to only one bucket
- The hybrid sync (rclone + wrangler) handles this automatically
- Or create a new token with access to both buckets

### Gallery not updating
```bash
just sync-gallery       # Force sync to gallery bucket
just deploy-gallery     # Redeploy Pages app
```

### Latest image not updating
```bash
just sync-latest        # Force upload latest image
just deploy-host        # Redeploy worker
```

### Check what's in R2
```bash
just r2-list            # Quick list
just r2-ls              # Detailed list with sizes/dates
```

## Technical Details

### rclone Configuration

Two remotes are configured:
- `r2:` → Points to account, used with `r2:dreamgen-gallery`
- `r2-latest:` → Points to account, used with `r2-latest:continuous-image-gen`

Both use the same credentials from your R2 API token.

### Sync Strategy

**Gallery (full collection)**:
```bash
rclone sync output/ r2:dreamgen-gallery --progress --transfers 8 --fast-list
```
- Mirrors local → remote
- Deletes files not in local (true sync)
- Fast with 8 parallel transfers

**Latest (most recent only)**:
```bash
# Find newest PNG
latest=$(find output -name "*.png" -type f -printf '%T@ %p\n' | sort -rn | head -1)

# Upload via wrangler (rclone fallback if token has access)
npx wrangler r2 object put "continuous-image-gen/$filename" --file "$latest"
```

## Future Improvements

1. **Unified Token**: Create R2 token with access to both buckets for pure rclone
2. **Automated Sync**: Set up cron job or systemd timer to auto-sync on new images
3. **Cloudflare Images**: Consider using Cloudflare Images for variants/optimization
4. **CDN Purge**: Auto-purge cache after uploads for instant updates
