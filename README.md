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
* **`GET /stores/{id}/metrics`**: Real-time sales metrics (visitor counts, conversions, queues, dwell times) utilizing the **5-minute pre-transaction billing counter correlation window**. Includes hourly traffic breakdown.
* **`GET /stores/{id}/funnel`**: Session-level conversion drop-off counts.
* **`GET /stores/{id}/zone-revenue`**: **NEW** Links CCTV zone-dwelling data with POS brand transactions to calculate GMV, conversion rate, and revenue contribution per physical shelf zone.
* **`GET /stores/{id}/heatmap`**: Normalized product brand visitor score allocations enriched with category labels and revenue contribution percentage.
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

* **Current Coverage:** **85% statement coverage** with 28 passing test specs verifying edge cases (zone-revenue mapping, zero-purchases, re-entries, group entries, staff exclusions, 503 DB errors, low-confidence propagation, and queue spikes).

## **Instructions To Run (For Reviewers)**

- **Prerequisites:** Install Docker and Docker Compose (desktop or CLI). Ensure Docker daemon is running.
- **Start the service (single command):** From the project root run:

```bash
cd Purplle
docker compose up -d --build
```

- **Verify the service is healthy:**

```bash
curl http://localhost:8000/health
```

- **Open the interactive UI and API docs:**

- Dashboard: http://localhost:8000/dashboard
- Swagger UI: http://localhost:8000/docs

- **Follow logs (optional):**

```bash
docker compose logs --no-color --follow
```

- **Run unit tests locally:** (requires Python & virtualenv)

```bash
python -m venv .venv
source .venv/bin/activate    # or `.venv\Scripts\Activate.ps1` on Windows PowerShell
pip install -r app/requirements.txt
python -m pytest --cov=app tests/
```

- **Stop and remove containers & volumes:**

```bash
docker compose down -v --rmi local
```

### Troubleshooting
- If the `/health` endpoint returns a POS CSV missing warning, place the provided Brigade CSV in the project root under its original path: `Problem Statement and Data Sources/Brigade_Bangalore_10_April_26 bc6219c.csv` and restart the service.
- The original CCTV video files were excluded from the public repository because they exceed GitHub file-size limits. To enable full pipeline replay with video files, copy the `CCTV Footage` folder into `Problem Statement and Data Sources/` before rebuilding the image.
- If `docker compose` fails with network or build errors, try increasing Docker's resources (CPU / memory) and retry the `docker compose up -d --build` command.

If you'd like, I can also add a tiny checklist of the four submission screenshots and capture them now while the service is running.
