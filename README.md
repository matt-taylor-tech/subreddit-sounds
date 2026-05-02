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

### Step 3 — Authenticate to GitHub to clone your private repo

You need to prove to GitHub who you are. The simplest way is a **Personal Access Token (PAT)**.

**Create a PAT on GitHub:**

1. Go to <https://github.com/settings/tokens>
1. Click **Generate new token (classic)**
1. Give it a name like `debian-server`
1. Check the `repo` scope
1. Click **Generate token** and copy it — you only see it once

**Clone the repo on your server** (replace `YOUR_GITHUB_USERNAME` and the repo name):

```bash
cd ~
git clone https://YOUR_GITHUB_USERNAME:YOUR_PAT_HERE@github.com/YOUR_GITHUB_USERNAME/ListigeClone.git
cd ListigeClone
```

> Your PAT is used only in this URL and is not stored anywhere else. If you
> prefer SSH keys instead, GitHub has a guide at
> <https://docs.github.com/en/authentication/connecting-to-github-with-ssh>.

---

### Step 4 — Create your `.env` file

Copy the example and fill in your credentials:

```bash
cp .env.example .env
nano .env
```

At minimum set these values (the rest can stay as defaults for now):

```
SECRET_KEY=some-long-random-string
ADMIN_USERNAME=admin
ADMIN_PASSWORD=a-strong-password

REDDIT_CLIENT_ID=your_reddit_app_id
REDDIT_CLIENT_SECRET=your_reddit_app_secret

SPOTIFY_CLIENT_ID=your_spotify_app_id
SPOTIFY_CLIENT_SECRET=your_spotify_app_secret
SPOTIFY_PLAYLIST_ID=the_id_from_your_playlist_url
```

Save and exit nano with `Ctrl+O`, `Enter`, `Ctrl+X`.

> **Security:** `.env` is in `.gitignore` so it will never be committed. Do
> not share it or paste it anywhere.

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
  --env-file ~/ListigeClone/.env \
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
| `--env-file` | Load your credentials from `.env` |
| `-v .../data:/app/data` | Mount host folder so the DB persists |

---

### Step 8 — Open the admin console

In your browser go to:

```
http://YOUR_SERVER_IP:8000/login
```

Log in with the `ADMIN_USERNAME` and `ADMIN_PASSWORD` you set in `.env`.

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
  --env-file ~/ListigeClone/.env \
  -v ~/ListigeClone/data:/app/data \
  listige-clone:latest
```

Your database in `~/ListigeClone/data/` is untouched across updates.

### Back up the database

```bash
cp ~/ListigeClone/data/listige.db ~/listige-backup-$(date +%Y%m%d).db
```

---

## Debian Deployment Notes

- Keep `.env` outside version control — it already is via `.gitignore`.
- Back up `~/ListigeClone/data/listige.db` regularly.
- For internet-facing access add Nginx + a free TLS cert via Certbot.
- Scheduler timezone is controlled by `SYNC_TIMEZONE=America/New_York` in `.env`.

## Tests

```bash
pytest
```
