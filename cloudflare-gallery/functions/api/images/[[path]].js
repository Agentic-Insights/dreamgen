export async function onRequestGet(ctx) {
  const path = ctx.params.path?.join('/') || '';

  // List all images with metadata
  if (!path) {
    const objects = await listAllObjects(ctx.env.GALLERY);
    const images = objects
      .filter(o => /\.(png|jpg|jpeg|webp|gif)$/i.test(o.key))
      .sort((a, b) => new Date(b.uploaded) - new Date(a.uploaded))
      .map(o => ({
        key: o.key,
        uploaded: o.uploaded,
        dateStr: extractDateFromFilename(o.key),
        captionKey: o.key.replace(/\.(png|jpg|jpeg|webp|gif)$/i, '.txt')
      }));
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
    txt: 'text/plain'
  };

  return new Response(file.body, {
    headers: {
      'Content-Type': file.httpMetadata?.contentType || contentTypes[ext] || 'application/octet-stream',
      'Cache-Control': ext === 'txt' ? 'public, max-age=3600' : 'public, max-age=31536000',
      'Access-Control-Allow-Origin': '*'
    }
  });
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

function extractDateFromFilename(filename) {
  // Extract YYYYMMDD from filename like "image_20251222_064746_16cd0ed1.png"
  const match = filename.match(/(\d{8})/);
  if (!match) return null;

  const dateStr = match[1];
  const year = dateStr.substring(0, 4);
  const month = dateStr.substring(4, 6);

  const date = new Date(year, parseInt(month) - 1, 1);
  return date.toLocaleString('en-US', { month: 'short', year: 'numeric' });
}
