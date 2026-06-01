# Apex Retail - Store Intelligence Analytics Platform
### Purplle Tech Challenge 2026 — Round 2 — Brigade Road Store (Bangalore)

This repository contains a complete, production-ready **Store Intelligence Platform** that processes raw CCTV security footage and correlates customer store activities with POS transaction logs to yield rich store-level conversions, heatmaps, and funnel insights.

---

## 🚀 Single-Command Startup

This repository is now configured so the entire API service starts with one command from the project root:

```bash
cd Purplle
docker compose up -d --build
```

That command builds the image, starts the API, and mounts the required runtime volumes.

Then verify the service is live with:

```bash
curl http://localhost:8000/health
```

If you need to ingest POS data or run the CCTV pipeline after startup, the commands are still available further below.

---

## 📊 Live Interactive Dashboard

Once you have run the CCTV pipeline to upload behavioral events, open your browser and navigate to:
👉 **[http://localhost:8000/dashboard](http://localhost:8000/dashboard)**

The interactive dark-mode dashboard features responsive animations utilizing **Chart.js** and polls metrics every 3 seconds to show live updates:
- **Conversion Funnel Stages:** (Entry $\rightarrow$ Visit $\rightarrow$ Queue $\rightarrow$ Purchase) with sequential drop-offs.
- **Brand Heatmap:** Visitor frequency and average dwell time per shelf segment.
- **Operational Anomalies Panel:** Highlighting cash counter queue spikes, dead zones, empty store alerts, and conversion drops.
- **Pipeline Health:** Verifying liveness and feed warnings.

---

## 🛠️ REST API Swagger Documentation

The FastAPI service exposes fully documented interactive Swagger endpoints:
👉 **[http://localhost:8000/docs](http://localhost:8000/docs)**

### Core Endpoints

* **`POST /events/ingest`**: Idempotent batch upload endpoint validating UUIDs and schemas. Handles duplicate posts using database constraints. Returns `207 Multi-Status` for partial success detail.
* **`GET /stores/{id}/metrics`**: Real-time sales metrics (visitor counts, conversions, queues, dwell times) utilizing the **5-minute pre-transaction billing counter correlation window**.
* **`GET /stores/{id}/funnel`**: Session-level conversion drop-off counts.
* **`GET /stores/{id}/heatmap`**: Normalized product brand visitor score allocations.
* **`GET /stores/{id}/anomalies`**: Operational flags.
* **`GET /health`**: Diagnostics reporting connection pool status and camera feed warning metrics.

---

## 🧪 Running Automated Unit Tests

To run the full diagnostic suite and verify code statement coverage:

```bash
# Install test requirements
pip install -r app/requirements.txt

# Run pytest coverage engine
python -m pytest --cov=app --cov-report=term-missing tests/
```

* **Current Coverage:** **75% statement coverage** with 15 passing test specs verifying edge cases (zero-purchases, re-entries, group entries, staff exclusions, 503 DB errors, low-confidence propagation, and queue spikes).
