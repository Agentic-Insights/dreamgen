const CURRENT_MANIFEST_KEY = '_dreamgen/current.json';

export async function onRequestGet(ctx) {
  const path = ctx.params.path?.join('/') || '';

  // The release manifest is the approval boundary and the canonical ordering.
  if (!path) {
    const manifest = await readJson(ctx.env.GALLERY, CURRENT_MANIFEST_KEY);
    if (isReleaseManifest(manifest)) {
      const images = manifest.items.map(item => buildManifestImageRecord(item, manifest));
      return Response.json(images, {
        headers: {
          'Cache-Control': 'no-store',
          'X-DreamGen-Release': manifest.release_id,
          'ETag': `"${manifest.release_id}"`
        }
      });
    }

    // Backward-compatible fallback before the first manifest-based publish.
    const objects = await listAllObjects(ctx.env.GALLERY);
    const objectKeys = new Set(objects.map(o => o.key));
    const imageObjects = objects
      .filter(o => /\.(png|jpg|jpeg|webp|gif)$/i.test(o.key))
      .sort((a, b) => sortTimestamp(b) - sortTimestamp(a) || a.key.localeCompare(b.key));

    const images = [];
    for (const object of imageObjects) {
      images.push(await buildImageRecord(ctx.env.GALLERY, object, objectKeys));
    }

    return Response.json(images, {
      headers: {
        'Cache-Control': 'no-store'
      }
    });
  }

  // Serve individual file (image or txt)
  const file = await ctx.env.GALLERY.get(path);
  if (!file) {
    return new Response('Not found', { status: 404 });
  }

  const ext = path.split('.').pop().toLowerCase();
  const contentTypes = {
    png: 'image/png',
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    webp: 'image/webp',
    gif: 'image/gif',
    txt: 'text/plain; charset=utf-8',
    json: 'application/json; charset=utf-8'
  };

  const requestUrl = new URL(ctx.request.url);
  const contentVersion = requestUrl.searchParams.get('v');
  const headers = new Headers({
    'Content-Type': file.httpMetadata?.contentType || contentTypes[ext] || 'application/octet-stream',
    'Cache-Control': contentVersion
      ? 'public, max-age=31536000, immutable'
      : 'public, max-age=300, must-revalidate',
    'Access-Control-Allow-Origin': '*'
  });
  if (file.httpEtag) headers.set('ETag', file.httpEtag);

  return new Response(file.body, { headers });
}

function isReleaseManifest(value) {
  return Boolean(
    value &&
    value.schema_version === 1 &&
    typeof value.release_id === 'string' &&
    Array.isArray(value.items)
  );
}

function buildManifestImageRecord(item, manifest) {
  const metadata = item.metadata && typeof item.metadata === 'object' ? item.metadata : {};
  const createdAt = item.created_at || metadata.generated_at || null;
  const createdDate = createdAt ? new Date(createdAt) : parseDateFromFilename(item.key);
  const backend = metadata.backend || metadata.provider || metadata.model_backend || 'unknown';
  const model = metadata.model || metadata.model_name || metadata.ollama_model || backend;
  const plugins = Array.isArray(metadata.plugins_used) ? metadata.plugins_used : [];
  const loras = Array.isArray(metadata.loras) ? metadata.loras : [];
  const publicationState = item.publication_state || metadata?.publication?.state || 'published';

  return {
    key: item.key,
    position: item.position,
    releaseId: manifest.release_id,
    assetVersion: item.asset_version,
    imageUrl: versionedAssetUrl(item.key, item.asset_version),
    uploaded: manifest.published_at,
    createdAt,
    approvedAt: item.approved_at || null,
    dateStr: formatMonthYear(createdDate),
    week: extractWeek(item.key),
    captionKey: item.caption_key || null,
    captionUrl: item.caption_key
      ? versionedAssetUrl(item.caption_key, item.caption_version || item.asset_version)
      : null,
    hasCaption: Boolean(item.caption_key),
    metadataKey: item.metadata_key || null,
    metadata,
    backend,
    model,
    plugins,
    loras,
    featured: publicationState === 'featured' || item.featured === true,
    publicationState,
    sharePath: `/?image=${encodeURIComponent(item.key)}`
  };
}

function versionedAssetUrl(key, version) {
  const encodedKey = String(key).split('/').map(encodeURIComponent).join('/');
  return `/api/images/${encodedKey}?v=${encodeURIComponent(version)}`;
}

async function buildImageRecord(bucket, object, objectKeys) {
  const captionKey = object.key.replace(/\.(png|jpg|jpeg|webp|gif)$/i, '.txt');
  const metadataKey = object.key.replace(/\.(png|jpg|jpeg|webp|gif)$/i, '.meta.json');
  const metadata = objectKeys.has(metadataKey) ? await readJson(bucket, metadataKey) : null;
  const parsedDate = parseDateFromFilename(object.key);
  const uploaded = object.uploaded ? new Date(object.uploaded).toISOString() : null;
  const createdAt = metadata?.generated_at || parsedDate?.toISOString() || uploaded || null;
  const backend = metadata?.backend || metadata?.provider || metadata?.model_backend || 'unknown';
  const model = metadata?.model || metadata?.model_name || metadata?.ollama_model || metadata?.backend || backend;
  const plugins = Array.isArray(metadata?.plugins_used) ? metadata.plugins_used : [];
  const loras = Array.isArray(metadata?.loras) ? metadata.loras : [];
  const publicationState = metadata?.publication?.state || metadata?.publication_state || 'published';

  return {
    key: object.key,
    uploaded,
    createdAt,
    dateStr: formatMonthYear(parsedDate || (createdAt ? new Date(createdAt) : null)),
    week: extractWeek(object.key),
    captionKey,
    hasCaption: objectKeys.has(captionKey),
    metadataKey: objectKeys.has(metadataKey) ? metadataKey : null,
    metadata,
    backend,
    model,
    plugins,
    loras,
    featured: publicationState === 'featured' || metadata?.featured === true,
    publicationState,
    sharePath: `/?image=${encodeURIComponent(object.key)}`
  };
}

async function readJson(bucket, key) {
  try {
    const object = await bucket.get(key);
    if (!object) return null;
    return JSON.parse(await object.text());
  } catch {
    return null;
  }
}

async function listAllObjects(bucket) {
  const objects = [];
  let cursor;

  do {
    const page = await bucket.list({ limit: 1000, cursor });
    objects.push(...page.objects);
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);

  return objects;
}

function sortTimestamp(object) {
  const fromName = parseDateFromFilename(object.key);
  if (fromName) return fromName.getTime();
  return object.uploaded ? new Date(object.uploaded).getTime() : 0;
}

function parseDateFromFilename(filename) {
  const match = filename.match(/(\d{4})(\d{2})(\d{2})(?:_(\d{2})(\d{2})(\d{2}))?/);
  if (!match) return null;
  return new Date(Date.UTC(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    Number(match[4] || 0),
    Number(match[5] || 0),
    Number(match[6] || 0)
  ));
}

function formatMonthYear(date) {
  if (!date || Number.isNaN(date.getTime())) return null;
  return date.toLocaleString('en-US', { month: 'short', year: 'numeric' });
}

function extractWeek(filename) {
  const match = filename.match(/(\d{4})\/(week_\d{2})\//);
  return match ? `${match[1]} ${match[2].replace('_', ' ')}` : null;
}
