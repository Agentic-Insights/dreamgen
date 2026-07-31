import { describe, expect, it } from 'vitest';
import { onRequestGet } from '../../cloudflare-gallery/functions/api/images/[[path]].js';

function objectBody(value: string, contentType = 'application/json') {
	const response = new Response(value, { headers: { 'Content-Type': contentType } });
	return {
		body: response.body,
		httpEtag: '"test-etag"',
		httpMetadata: { contentType },
		text: () => Promise.resolve(value),
	};
}

function context(bucket: unknown, path: string[] = [], url = 'https://example.com/api/images') {
	return {
		params: { path },
		env: { GALLERY: bucket },
		request: new Request(url),
	} as never;
}

describe('manifest-driven gallery API', () => {
	it('uses exact approved release order and ignores stale bucket listing order', async () => {
		let listCalled = false;
		const manifest = {
			schema_version: 1,
			release_id: 'release-20260731',
			published_at: '2026-07-31T22:00:00Z',
			items: [
				{
					position: 0,
					key: '2026/week_29/image_20260714_020519_current.png',
					asset_version: 'current-version',
					created_at: '2026-07-14T02:05:19Z',
					approved_at: '2026-07-15T17:22:05Z',
					publication_state: 'published',
					caption_key: null,
					metadata_key: null,
					metadata: { backend: 'mage-flow', model: 'Mage-Flow' },
				},
				{
					position: 1,
					key: '2026/week_17/image_20260425_141420_older.png',
					asset_version: 'older-version',
					created_at: '2026-04-25T14:14:20Z',
					publication_state: 'published',
					caption_key: null,
					metadata_key: null,
					metadata: {},
				},
			],
		};
		const bucket = {
			async get(key: string) {
				return key === '_dreamgen/current.json' ? objectBody(JSON.stringify(manifest)) : null;
			},
			async list() {
				listCalled = true;
				return { objects: [], truncated: false };
			},
		};

		const response = await onRequestGet(context(bucket));
		const images = (await response.json()) as Array<Record<string, unknown>>;

		expect(response.headers.get('X-DreamGen-Release')).toBe('release-20260731');
		expect(listCalled).toBe(false);
		expect(images.map((item) => item.key)).toEqual([
			'2026/week_29/image_20260714_020519_current.png',
			'2026/week_17/image_20260425_141420_older.png',
		]);
		expect(images[0].imageUrl).toBe(
			'/api/images/2026/week_29/image_20260714_020519_current.png?v=current-version',
		);
	});

	it('makes versioned assets immutable and unversioned assets revalidate', async () => {
		const bucket = {
			async get(key: string) {
				return key.endsWith('.png') ? objectBody('image', 'image/png') : null;
			},
		};

		const versioned = await onRequestGet(
			context(
				bucket,
				['approved.png'],
				'https://example.com/api/images/approved.png?v=content-hash',
			),
		);
		const unversioned = await onRequestGet(
			context(bucket, ['approved.png'], 'https://example.com/api/images/approved.png'),
		);

		expect(versioned.headers.get('Cache-Control')).toBe('public, max-age=31536000, immutable');
		expect(unversioned.headers.get('Cache-Control')).toBe(
			'public, max-age=300, must-revalidate',
		);
		expect(versioned.headers.get('ETag')).toBe('"test-etag"');
	});

	it('falls back to full filename timestamps before the first manifest publish', async () => {
		const objects = [
			{ key: 'image_20260731_120000_a.png', uploaded: new Date('2026-07-31T22:00:00Z') },
			{ key: 'image_20260731_130000_b.png', uploaded: new Date('2026-07-31T21:00:00Z') },
		];
		const bucket = {
			async get() {
				return null;
			},
			async list() {
				return { objects, truncated: false };
			},
		};

		const response = await onRequestGet(context(bucket));
		const images = (await response.json()) as Array<Record<string, unknown>>;

		expect(images.map((item) => item.key)).toEqual([
			'image_20260731_130000_b.png',
			'image_20260731_120000_a.png',
		]);
	});
});
