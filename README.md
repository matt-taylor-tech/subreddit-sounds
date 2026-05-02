# Listige Clone

Self-hosted Reddit-to-Spotify sync app with a built-in admin console.

## Current Implementation Status

This initial implementation includes:

- FastAPI app with server-rendered admin UI
- Single local admin login
- SQLite persistence
- Daily in-app scheduler configured for `07:00 America/New_York`
- Manual run trigger + run history pages
- Docker single-container deployment path

Spotify and Reddit API integration logic is scaffolded and ready for the next implementation pass.

## Quick Start (Local)

1. Create and activate a virtual environment.
1. Install dependencies:

```bash
pip install -r requirements.txt
```

1. Copy env template:

```bash
cp .env.example .env
```

1. Start app:

```bash
uvicorn app.main:app --reload
```

1. Open `http://localhost:8000/login`.

## Quick Start (Single Docker Container)

1. Build image:

```bash
docker build -t listige-clone:0.1.0 .
```

1. Create local data directory:

```bash
mkdir -p ./data
```

1. Run container:

```bash
docker run -d \
  --name listige-clone \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  listige-clone:0.1.0
```

1. Visit `http://YOUR_HOST:8000/login`.

## Debian Deployment Notes

- Keep `.env` outside version control.
- Back up `./data/listige.db` daily.
- Use reverse proxy + TLS (Nginx/Caddy) for internet exposure.
- If changing timezone behavior, set `SYNC_TIMEZONE=America/New_York` and keep `SYNC_HOUR=7`.

## Tests

```bash
pytest
```
