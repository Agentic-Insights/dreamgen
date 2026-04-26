import { describe, expect, it } from 'vitest';
import worker, { type Env } from '../src/index';

function createEnv(objects: Array<{ key: string; uploaded: Date; body?: string }>): Env {
	const bodies = new Map(
		objects.map((object) => [
			object.key,
			new Response(object.body ?? `body:${object.key}`, {
				headers: { 'Content-Type': 'image/png' },
			}),
		]),
	);

	return {
		DREAM_BUCKET: {
			async list() {
				return {
					objects,
					truncated: false,
				};
			},
			async get(key: string) {
				const response = bodies.get(key);
				if (!response) return null;
				return {
					body: response.body,
					httpMetadata: { contentType: response.headers.get('Content-Type') ?? undefined },
				};
			},
		} as unknown as R2Bucket,
	};
}

describe('host-image worker', () => {
	it('rejects non-GET requests', async () => {
		const response = await worker.fetch(new Request('https://example.com', { method: 'POST' }), createEnv([]));

		expect(response.status).toBe(405);
		expect(await response.text()).toBe('Method not allowed');
	});

	it('returns 404 when no images are available', async () => {
		const response = await worker.fetch(new Request('https://example.com'), createEnv([]));

		expect(response.status).toBe(404);
		expect(await response.text()).toBe('No images found');
	});

	it('serves the most recently uploaded PNG image', async () => {
		const response = await worker.fetch(
			new Request('https://example.com'),
			createEnv([
				{ key: 'older.png', uploaded: new Date('2026-04-01T00:00:00Z'), body: 'older' },
				{ key: 'newer.png', uploaded: new Date('2026-04-02T00:00:00Z'), body: 'newer' },
				{ key: 'newer.txt', uploaded: new Date('2026-04-03T00:00:00Z'), body: 'prompt' },
			]),
		);

		expect(response.status).toBe(200);
		expect(response.headers.get('Content-Type')).toBe('image/png');
		expect(response.headers.get('X-Image-Name')).toBe('newer.png');
		expect(new TextDecoder().decode(await response.arrayBuffer())).toBe('newer');
	});
});
