export async function onRequestGet(ctx) {
  const path = ctx.params.path?.join('/') || '';

  // List all images with optional prompt/metadata sidecars.
  if (!path) {
    const objects = await listAllObjects(ctx.env.GALLERY);
    const objectKeys = new Set(objects.map(o => o.key));
    const imageObjects = objects
      .filter(o => /\.(png|jpg|jpeg|webp|gif)$/i.test(o.key))
      .sort((a, b) => sortTimestamp(b) - sortTimestamp(a));

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

  return new Response(file.body, {
    headers: {
      'Content-Type': file.httpMetadata?.contentType || contentTypes[ext] || 'application/octet-stream',
      'Cache-Control': ext === 'txt' ? 'public, max-age=3600' : 'public, max-age=31536000',
      'Access-Control-Allow-Origin': '*'
    }
  });
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
  const match = filename.match(/(\d{8})/);
  if (!match) return null;

  const dateStr = match[1];
  const year = dateStr.substring(0, 4);
  const month = dateStr.substring(4, 6);
  const day = dateStr.substring(6, 8);

  return new Date(Number(year), Number(month) - 1, Number(day));
}

function formatMonthYear(date) {
  if (!date || Number.isNaN(date.getTime())) return null;
  return date.toLocaleString('en-US', { month: 'short', year: 'numeric' });
}

function extractWeek(filename) {
  const match = filename.match(/(\d{4})\/(week_\d{2})\//);
  return match ? `${match[1]} ${match[2].replace('_', ' ')}` : null;
}
