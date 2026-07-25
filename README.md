# Hyperspace

Hyperspace runs the same production FastAPI and PostgreSQL services locally for the live demo.

## Run the demo on this Mac

Start the production stack on port 8000 using this Mac's LAN address:

```bash
just demo
```

The command prints the URL to open on demo devices:

```text
Demo: http://192.168.1.23:8000
```

`docker-compose.demo.yml` only publishes FastAPI and sets the QR-code URL. `docker-compose.production.yml` defines the production services.

## Deploy committed code

Commit every change, then deploy `main`:

```bash
git commit
git push origin main
just deploy
```

`just deploy` pushes `main`, then connects directly to the Droplet's public SSH address.

The Droplet fetches `origin/main`, force-checks it out in detached mode, rebuilds FastAPI, and waits for healthy containers.

## Update code on the Droplet

For a last-minute fix, edit the host checkout and restart FastAPI:

```bash
ssh digitalocean
cd /opt/hyperspace/app
# Edit files.
docker restart hyperspace-fastapi-1
curl -fsS https://hyperspace.christiantanul.com/health
```

The health check prints `ok`.

Edit the writable host checkout. Docker reads it through the read-only `/code` bind.

A normal deploy replaces direct Droplet edits with committed `origin/main`. Use a normal deploy for dependency changes so Docker rebuilds the FastAPI image.
