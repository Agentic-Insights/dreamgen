export interface Env {
	DREAM_BUCKET: R2Bucket;
}

const IMAGE_CACHE_SECONDS = 300;

function jsonResponse(payload: unknown, init: ResponseInit = {}) {
	const headers = new Headers(init.headers);
	headers.set('Content-Type', 'application/json');
	headers.set('Access-Control-Allow-Origin', '*');

	return new Response(JSON.stringify(payload, null, 2), {
		...init,
		headers,
	});
}

export default {
	async fetch(request: Request, env: Env) {
		// Only allow GET requests
		if (request.method !== 'GET') {
			return new Response('Method not allowed', { status: 405 });
		}

		try {
			const url = new URL(request.url);

			if (url.pathname === '/health') {
				return jsonResponse({
					status: 'ok',
					service: 'host-image',
					cache_seconds: IMAGE_CACHE_SECONDS,
				});
			}

			// List all images and get the most recent one
			const list = await env.DREAM_BUCKET.list();
			if (!list.objects || list.objects.length === 0) {
				if (url.pathname === '/metadata') {
					return jsonResponse({ error: 'No PNG images found', image_count: 0 }, { status: 404 });
				}
				return new Response('No images found', { status: 404 });
			}

			// Filter for PNG images and sort by uploaded date (most recent first)
			const images = list.objects
				.filter((obj) => obj.key.endsWith('.png'))
				.sort((a, b) => new Date(b.uploaded).getTime() - new Date(a.uploaded).getTime());
			if (images.length === 0) {
				if (url.pathname === '/metadata') {
					return jsonResponse({ error: 'No PNG images found', image_count: 0 }, { status: 404 });
				}
				return new Response('No PNG images found', { status: 404 });
			}

			// Get the most recent image
			const latestImage = images[0];
			if (url.pathname === '/metadata') {
				return jsonResponse({
					latest_key: latestImage.key,
					latest_uploaded: latestImage.uploaded,
					image_count: images.length,
					cache_seconds: IMAGE_CACHE_SECONDS,
				});
			}

			const object = await env.DREAM_BUCKET.get(latestImage.key);

			if (!object) {
				return new Response('Image not found', { status: 404 });
			}

			// Set up headers
			const headers = new Headers();
			headers.set('Content-Type', 'image/png');
			headers.set('Cache-Control', `public, max-age=${IMAGE_CACHE_SECONDS}`); // Cache briefly to show updates faster
			headers.set('Access-Control-Allow-Origin', '*'); // Allow CORS
			headers.set('X-Image-Name', latestImage.key); // Show which image is being served

			return new Response(object.body, {
				headers,
				status: 200,
			});
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			return new Response(`Error: ${message}`, { status: 500 });
		}
	},
};
