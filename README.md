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

1. Start app (no `.env` needed — a secret key is auto-generated on first run):

```bash
uvicorn app.main:app --reload
```

1. Open `http://localhost:8000/` and complete the first-run setup wizard.

## Deploying on Your Debian Server (First Time)

This walks through every step from a fresh SSH session to a running container.
No prior Docker experience required.

### Step 1 — SSH into your Debian server

From your Windows machine open a terminal and connect:

```bash
ssh youruser@YOUR_SERVER_IP
```

---

### Step 2 — Install Docker (if not already installed)

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io
```

Verify Docker is running:

```bash
sudo docker run hello-world
```

Optionally allow your user to run Docker without `sudo` (requires logout/login to take effect):

```bash
sudo usermod -aG docker $USER
```

---

### Step 3 — Clone the repo

The repository is public, so no authentication is needed:

```bash
cd ~
git clone https://github.com/matt-taylor-tech/ListigeClone.git
cd ListigeClone
```

---

### Step 4 — (Optional) `.env` file

**You can skip this step.** With no `.env` at all, the app boots on sane
defaults and auto-generates a persistent session-signing key in the data
volume on first run. All API credentials (Reddit, Spotify), the admin login,
and sync options are entered later in the web setup wizard and stored in the
database.

Create a `.env` only if you want to override a default — for example a custom
host port, or managing the secret key yourself:

```bash
cp .env.example .env
nano .env   # everything is commented out; uncomment only what you need
```

> **Security:** `.env` is in `.gitignore` so it is never committed.

---

### Step 5 — Create the data directory

This is where the database and logs are stored. It lives outside the
container so data survives restarts and upgrades.

```bash
mkdir -p ~/ListigeClone/data
```

---

### Step 6 — Build the Docker image

This reads the `Dockerfile` and packages the app into a self-contained image.
It only needs to run once (and again after updates).

```bash
cd ~/ListigeClone
docker build -t listige-clone:0.1.0 .
```

You will see output as each layer is built. It takes 1–3 minutes the first time.

---

### Step 7 — Run the container

```bash
docker run -d \
  --name listige-clone \
  --restart unless-stopped \
  -p 8000:8000 \
  -v ~/ListigeClone/data:/app/data \
  listige-clone:0.1.0
```

What each flag does:

| Flag | Purpose |
|------|---------|
| `-d` | Run in background (detached) |
| `--name listige-clone` | Give it a memorable name |
| `--restart unless-stopped` | Auto-restart after reboots |
| `-p 8000:8000` | Expose port 8000 on the host |
| `-v .../data:/app/data` | Mount host folder so the DB (and secret key) persist |

> Only if you created an optional `.env` (Step 4), add `--env-file ~/ListigeClone/.env` to the command.

---

### Step 8 — Open the admin console

In your browser go to:

```
http://YOUR_SERVER_IP:8000/login
```

The first visit redirects you to `/setup`, where you create the admin login
and enter your Reddit/Spotify credentials. After that, log in with the admin
username and password you chose there.

---

## Day-to-Day Operations

### Check if the container is running

```bash
docker ps
```

### View logs

```bash
docker logs listige-clone
# Follow live:
docker logs -f listige-clone
```

### Stop / start

```bash
docker stop listige-clone
docker start listige-clone
```

### Updating to a new version

```bash
cd ~/ListigeClone
git pull
docker build -t listige-clone:latest .
docker stop listige-clone
docker rm listige-clone
docker run -d \
  --name listige-clone \
  --restart unless-stopped \
  -p 8000:8000 \
  -v ~/ListigeClone/data:/app/data \
  listige-clone:latest
```

Your database and secret key in `~/ListigeClone/data/` are untouched across updates.

### Back up the database

```bash
cp ~/ListigeClone/data/listige.db ~/listige-backup-$(date +%Y%m%d).db
```

---

## Running on a different port

The container always listens on `8000` internally; you choose the **host** port.

- **docker run:** change the left side of `-p`, e.g. `-p 9000:8000` serves it on host port 9000.
- **docker compose:** set `APP_PORT` in `.env` (e.g. `APP_PORT=9000`); it defaults to 8000.

## Security

- The session-signing key is auto-generated and persisted to the data volume on
  first run — no manual step. Keep the `data/` volume private, since it holds
  that key and the database.
- If you'd rather manage the key yourself, set `SECRET_KEY` in `.env`; with
  `ENVIRONMENT=production` the app refuses to start on a known placeholder value.
- Set the admin credentials during the first-run setup wizard.
- For internet-facing access, put it behind Nginx with a free TLS cert via
  Certbot rather than exposing port 8000 directly.
- All API secrets live in the database volume, never in the repo or image.

## Debian Deployment Notes

- `.env` is optional; if you create one, it's already outside version control via `.gitignore`.
- Back up `~/ListigeClone/data/listige.db` regularly.
- Scheduler timezone is set in the setup wizard (default `America/New_York`).

## Tests

```bash
pytest
```
