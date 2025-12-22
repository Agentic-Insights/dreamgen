interface Env {
	DREAM_BUCKET: R2Bucket;
}

export default {
	async fetch(request: Request, env: Env) {
		// Only allow GET requests
		if (request.method !== 'GET') {
			return new Response('Method not allowed', { status: 405 });
		}

		try {
			// List all images and get the most recent one
			const list = await env.DREAM_BUCKET.list();

			if (!list.objects || list.objects.length === 0) {
				return new Response('No images found', { status: 404 });
			}

			// Filter for PNG images and sort by uploaded date (most recent first)
			const images = list.objects
				.filter(obj => obj.key.endsWith('.png'))
				.sort((a, b) => new Date(b.uploaded).getTime() - new Date(a.uploaded).getTime());

			if (images.length === 0) {
				return new Response('No PNG images found', { status: 404 });
			}

			// Get the most recent image
			const latestImage = images[0];
			const object = await env.DREAM_BUCKET.get(latestImage.key);

			if (!object) {
				return new Response('Image not found', { status: 404 });
			}

			// Set up headers
			const headers = new Headers();
			headers.set('Content-Type', 'image/png');
			headers.set('Cache-Control', 'public, max-age=300'); // Cache for 5 minutes to show updates faster
			headers.set('Access-Control-Allow-Origin', '*'); // Allow CORS
			headers.set('X-Image-Name', latestImage.key); // Show which image is being served

			return new Response(object.body, {
				headers,
				status: 200
			});
		} catch (error) {
			return new Response(`Error: ${error.message}`, { status: 500 });
		}
	}
}
