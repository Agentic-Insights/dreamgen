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
just publish-gallery   # Dry-run approved gallery publishing
just -- publish-gallery --execute  # Publish approved gallery assets
just publish-gallery-smoke # Validate remote R2 write/delete access
just sync-gallery      # Legacy raw rclone mirror of output/
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

### Automated code deploys

Cloudflare code deployment is automated by `.github/workflows/cloudflare-deploy.yml`.
On pushes to `main` that change `cloudflare-gallery/**`, `host-image/**`, or the workflow
itself, GitHub Actions deploys:

- `cloudflare-gallery` to the `dreamgen-gallery` Pages project.

The workflow can also be run manually from GitHub Actions with `workflow_dispatch`.
The manual run can optionally deploy `host-image` to the `host-image` Worker when
`deploy_host` is enabled. It expects these repository secrets:

- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`

The API token used for `host-image` Worker deployment must include Workers edit/deploy
permissions in addition to Pages permissions. Tokens scoped only for Pages should leave
`deploy_host` disabled.

Generated image publishing is still a separate local step because `output/` is ignored
and may contain local mock/test artifacts. Use `just publish-gallery` first to preview
the non-placeholder assets that would be uploaded, then run:

```bash
just publish-gallery-smoke
just -- publish-gallery --execute
```

`scripts/publish_gallery.py` skips image files whose `.meta.json` sidecar marks them
as `is_placeholder` or `backend: mock`, and includes matching `.txt` prompt sidecars.
It uses remote R2 by default through Wrangler; pass `--local` only when intentionally
testing Wrangler's local R2 simulation.

Cloudflare's R2 token documentation lists the relevant write permissions as
`Workers R2 Storage Write` at the account level, or `Workers R2 Storage Bucket Item Write`
for scoped bucket object access. The token used by this repository must be able to write
objects in the `dreamgen-gallery` bucket for `just publish-gallery-smoke` and publishing
to succeed.

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
