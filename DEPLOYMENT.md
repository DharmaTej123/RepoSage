# Deployment

RepoSage deploys as a small set of containers. The backend API and the RQ
worker share one image (backend/Dockerfile); the datastores are managed
services or containers.

## Services

- backend (API): uvicorn app.main:app on :8000
- worker: python -m app.worker (consumes the reposage RQ queue)
- postgres: pgvector-enabled Postgres (system of record + vector index)
- redis: job queue
- neo4j: structural knowledge graph

## Local (docker compose)

```
docker compose up -d            # datastores
docker build -f backend/Dockerfile -t reposage-backend .
docker run --env-file backend/.env -p 8000:8000 reposage-backend
docker run --env-file backend/.env reposage-backend python -m app.worker
```

Build the sandbox image once so the coverage agent can run:

```
docker build -t reposage-sandbox:latest infra/sandbox
```

The worker needs access to the Docker daemon to launch sandbox containers
(mount the docker socket, e.g. -v /var/run/docker.sock:/var/run/docker.sock).
Sandbox containers themselves run with network=none and strict limits.

## Railway / managed pattern

- Provision managed Postgres (with pgvector), Redis, and Neo4j.
- Deploy the backend image as a web service (start: uvicorn app.main:app).
- Deploy the same image as a worker service (start: python -m app.worker).
- Set REPOSAGE_* env vars (see backend/.env.example) to the managed
  connection strings.
- Build and publish the frontend (npm run build) as static assets served by a
  CDN / static host, pointed at the backend base URL.

## Configuration

All tunables are REPOSAGE_-prefixed environment variables (repo size limits,
history window, thresholds, sandbox CPU/memory/timeout/pids, LLM budget,
LangSmith tracing). See backend/.env.example.