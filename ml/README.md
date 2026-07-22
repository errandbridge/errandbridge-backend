# ErrandBridge ML (local)

This folder contains a lightweight Python service intended to evolve from deterministic heuristics (today) into ML-powered scoring (later).

## Endpoints

- `GET /health` - liveness probe
- `POST /score` - returns tags / priority / reasons (deterministic rules for now)
- `GET /metrics` - Prometheus metrics

## Running (via docker-compose)

This service is run by `../docker-compose.yml` as `ml`, alongside:
- `api` (main FastAPI app)
- `db` (Postgres)
- `prometheus`
- `grafana`

The main API can optionally call this service via internal network URL: `http://ml:8010`.
