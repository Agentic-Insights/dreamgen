export async function onRequestGet(ctx) {
  const path = ctx.params.path?.join('/') || '';

  // List all images with metadata
  if (!path) {
    const list = await ctx.env.GALLERY.list();
    const images = list.objects
      .filter(o => /\.(png|jpg|jpeg|webp|gif)$/i.test(o.key))
      .sort((a, b) => new Date(b.uploaded) - new Date(a.uploaded))
      .map(o => ({
        key: o.key,
        uploaded: o.uploaded,
        dateStr: extractDateFromFilename(o.key)
      }));
    return Response.json(images);
  }

  // Serve individual image
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
    gif: 'image/gif'
  };

  return new Response(file.body, {
    headers: {
      'Content-Type': file.httpMetadata?.contentType || contentTypes[ext] || 'image/png',
      'Cache-Control': 'public, max-age=31536000',
      'Access-Control-Allow-Origin': '*'
    }
  });
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
