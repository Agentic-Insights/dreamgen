## DreamGen Web UI

This frontend is the Next.js interface for DreamGen.

### Local dev

```bash
npm install
npm run dev
```

By default Next.js serves the app at `http://localhost:3000`.

The frontend expects the DreamGen API on `http://localhost:25800` unless `NEXT_PUBLIC_API_URL` is set.

### Production-style local run

Use the repo-level Docker flow if you want the same ports and wiring used by the shipped app:

```bash
docker compose --env-file .env.docker up --build
```

That exposes:

- UI: `http://localhost:7860`
- API: `http://localhost:25800`
