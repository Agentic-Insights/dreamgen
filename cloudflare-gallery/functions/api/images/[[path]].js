export async function onRequestGet(ctx) {
  const path = ctx.params.path?.join('/') || '';

  // List all images
  if (!path) {
    const list = await ctx.env.GALLERY.list();
    const keys = list.objects
      .filter(o => /\.(png|jpg|jpeg|webp|gif)$/i.test(o.key))
      .sort((a, b) => new Date(b.uploaded) - new Date(a.uploaded))
      .map(o => o.key);
    return Response.json(keys);
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
