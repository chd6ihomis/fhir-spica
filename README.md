# PHeRef Web Portal

A UI-based **Health Information Exchange (HIE)** with eReferral integration for the
**June 2026 Philippines FHIR® Connectathon**. It implements the Philippine eReferral
(PHeRef) workflow on top of the **PH Core** and **PH eReferral** Implementation Guides,
using the Ana Reyes sample case as the reference scenario.

The portal is a thin orchestration layer: **all clinical data lives on the FHIR
Transactional Server** and **all codes come from the Terminology Server** — nothing
clinical is persisted locally. Only operational configuration is stored on disk.

---

## Table of contents
1. [Features](#features)
2. [Architecture](#architecture)
3. [Quick start (Python venv)](#quick-start-python-venv)
4. [Quick start (Docker)](#quick-start-docker)
5. [Initialization & first use](#initialization--first-use)
6. [Configuration reference](#configuration-reference)
7. [Accessing the portal](#accessing-the-portal)
8. [API reference](#api-reference)
9. [Testing](#testing)
10. [Troubleshooting](#troubleshooting)
11. [Project layout](#project-layout)

---

## Features

| Capability | Where | Spec mapping |
|---|---|---|
| Submit an eReferral as a single atomic **20-entry transaction Bundle** | `/submit` | UC1 (PUT master / POST clinical) |
| Conditional **PUT upsert** of master data, **POST** of clinical data | bundle builder | Idempotent master data |
| **Module console** — every Bundle entry as a granular, previewable FHIR operation (method/URL badges, hover field docs, GET fetch, master upsert) | `/modules` | PH eReferral Postman collection |
| **Patient masterlist** + duplicate pre-check | `/patients` | GET /Patient dedup |
| **Referral worklist** with status filter/sort | `/worklist` | UC2 receiving facility |
| **Task state machine** transitions via PATCH (PUT fallback) | `/worklist` | requested→received→accepted→completed / rejected |
| **Terminology-driven** dropdowns (SNOMED/LOINC/PSA) via `ValueSet/$expand` | all forms | UC0 GET terminology |
| **PSA PSGC** geographic address extensions (region/province/city/barangay) | `/submit` | PH Core address slices |
| **Admin portal** for server URLs, PSA version, auth tokens | `/admin` | Portal administration |
| **Developer suite**: raw JSON viewer, API request/response logger, OperationOutcome parser, code lookup | `/debug` | Debugging suite |

---

## Architecture

```
Browser ──HTTP──► FastAPI portal ──► FHIR Transactional Server (clinical data)
                       │            ─► FHIR Terminology Server  (ValueSet/$expand, $lookup)
                       │            ─► PSA Classification API    (PSGC geography)
                       └─ runtime config (config/runtime-config.json)
```

* **Backend:** FastAPI + httpx (async). Every outbound call is timed and logged.
* **Frontend:** server-rendered Jinja2 templates + vanilla JS (no Node build step).
* **Default servers** (override in `/admin` or `.env`):
  * FHIR Transactional: `https://cdr.pheref.fhirlab.net/fhir`
  * Terminology: `https://tx.fhirlab.net/fhir`
  * PSA: `https://classification.psa.gov.ph`

---

## Quick start (Python venv)

> Requires **Python 3.11 or 3.12** (the pinned `pydantic-core` ships prebuilt wheels for
> these; 3.13/3.14 may require a Rust toolchain to build from source).

### Windows (PowerShell)
```powershell
cd pheref-portal
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # optional: edit values
python run.py
```

### Linux / macOS
```bash
cd pheref-portal
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # optional: edit values
python run.py
```

The portal starts on **http://localhost:8000**. Use `uvicorn app.main:app --reload`
during development for auto-reload.

---

## Quick start (Docker)

```bash
cd pheref-portal
docker compose up --build      # http://localhost:8000
```

or with plain Docker:

```bash
cd pheref-portal
docker build -t pheref-portal .
docker run -p 8000:8000 -v "$(pwd)/config:/app/config" pheref-portal
```

The bind-mount on `./config` persists any configuration you change through the Admin
portal across container restarts. Override any setting via `-e PHEREF_...` flags or the
`docker-compose.yml` environment block.

---

## Initialization & first use

1. Open **http://localhost:8000** — the **Dashboard** shows the active servers and a
   live connectivity indicator (green dot = FHIR server reachable).
2. Go to **Admin** (`/admin`) and confirm/adjust the FHIR, Terminology, and PSA
   endpoints. Click **Test connection** — you should see the server software
   (e.g. *HAPI FHIR Server, FHIR 4.0.1*). For the Connectathon, set **PSA API Version**
   to `Q1_2026` if instructed.
3. Go to **Submit eReferral** (`/submit`). Click **Load Ana Reyes defaults** to
   pre-fill the canonical scenario. Coded fields and the address hierarchy load from
   the Terminology and PSA servers (a `server`/`fallback` tag shows the data source).
4. Click **Check for duplicate patient** to run the pre-submission dedup GET, then
   **Preview Bundle** to inspect the 20-entry transaction, then **Submit eReferral**.
5. The result panel lists created resource IDs and any parsed `OperationOutcome`
   issues. Switch to **Worklist** (`/worklist`) to see the new referral and advance
   its Task through `received → accepted → completed`.

### Module Console (`/modules`)

The eReferral is always submitted as one atomic transaction **Bundle**. The Module
Console mirrors the PH eReferral Postman collection by exposing each Bundle entry as
an individually inspectable FHIR operation — useful for debugging structure and for
updating a single master record.

- **Open it** from the **Submit** form (*Open Module Console* — your current form is
  carried over), or directly at `/modules` and click **Load last form**. **Load sample
  (Ana Reyes)** seeds the IG demo dataset for testing only.
- Each card shows a **method + URL badge** (PUT upsert for master resources, POST for
  clinical), a **Preview JSON** view where **hovering any field name** reveals its FHIR
  meaning, **Fetch existing (GET)** to read the current server copy of a master record,
  and **Send** to upsert a single master resource.
- Clinical resources depend on records the Bundle creates, so they are submitted via the
  **Submit Bundle** action on the Bundle card (not individually).

> **No fallback / no assumed clinical data.** Patient data is exactly what the user
> encodes. The `DEFAULTS` sample is opt-in (`use_defaults`) and only ever applies to a
> *completely empty* form. The API **rejects** (HTTP 400) any request that tries to mix
> sample defaults with real, partially-entered data, so missing fields are never silently
> back-filled with assumed values — they are simply omitted from the payload.

---

## Configuration reference

Settings resolve in this order: **defaults → environment / `.env` → Admin overrides
(`config/runtime-config.json`)**. Admin overrides win and apply immediately.

| Env var | Admin field | Default | Purpose |
|---|---|---|---|
| `PHEREF_FHIR_BASE_URL` | FHIR Transactional Server URL | `https://cdr.pheref.fhirlab.net/fhir` | Clinical resource storage/retrieval |
| `PHEREF_TERMINOLOGY_BASE_URL` | FHIR Terminology Server URL | `https://tx.fhirlab.net/fhir` | `ValueSet/$expand`, `CodeSystem/$lookup` |
| `PHEREF_PSA_BASE_URL` | PSA Base URL | `https://classification.psa.gov.ph` | PSGC geography |
| `PHEREF_PSA_VERSION` | PSA API Version | `Q2_2024` | Target PSA dataset (Connectathon: `Q1_2026`) |
| `PHEREF_PSA_TOKEN` | PSA API Token | _(blank)_ | PSA access token (write-only) |
| `PHEREF_FHIR_AUTH_TOKEN` | FHIR Authentication Token | _(blank)_ | Bearer token for FHIR + terminology (write-only) |
| `PHEREF_HTTP_TIMEOUT` | HTTP timeout (seconds) | `30` | Outbound request timeout |
| `PHEREF_HOST` / `PHEREF_PORT` | — | `0.0.0.0` / `8000` | Bind address |

Secrets (`*_TOKEN`) are never returned by the API — the Admin form shows only whether a
value is set; leave the field blank to keep the current secret.

---

## Accessing the portal

| Page | Path | Description |
|---|---|---|
| Dashboard | `/` | Status, referral counters, environment summary |
| Submit eReferral | `/submit` | Build & submit the transaction Bundle |
| Module Console | `/modules` | Granular per-resource FHIR operations (preview, fetch, upsert) |
| Patient Masterlist | `/patients` | Search patients, dedup |
| Referral Worklist | `/worklist` | Receiving-facility Task list + transitions |
| Admin | `/admin` | Environment configuration |
| Developer Tools | `/debug` | API log, OperationOutcome parser, code lookup |
| OpenAPI docs | `/docs` | Interactive Swagger UI |
| Liveness | `/healthz` | Process health (used by the Docker healthcheck) |

---

## API reference

All UI data flows through these JSON endpoints (full schema at `/docs`):

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Portal + FHIR server reachability probe |
| `GET/PUT /api/config` | Read / update runtime configuration |
| `GET /api/terminology/expand?url=<key|canonical>` | Expand a ValueSet |
| `GET /api/terminology/lookup?system=&code=` | CodeSystem `$lookup` |
| `GET /api/psa/{regions|provinces|municipalities|barangays}?parent=` | PSGC geography |
| `GET /api/referral/defaults` | Ana Reyes default field values |
| `POST /api/referral/preview` | Build (not submit) the Bundle |
| `POST /api/referral/submit` | Build + POST the transaction Bundle |
| `POST /api/modules/preview` | Decompose the form into granular module descriptors (method/URL/resource/refs) |
| `GET /api/modules/field-docs` | FHIR field → description map (console hover tooltips) |
| `POST /api/modules/fetch` | GET the existing server copy of a master module by identifier |
| `POST /api/modules/submit` | Submit one module (conditional PUT upsert for master resources) |
| `POST /api/modules/bundle/{preview,submit}` | Canonical Bundle preview/submit from the console |
| `GET /api/patients?name=&identifier=` | Patient masterlist |
| `GET /api/patients/check?system=&value=` | Duplicate pre-check |
| `GET /api/referrals?status=&owner=` | Referral (Task) worklist |
| `GET /api/referrals/{task_id}` | Full referral detail (Task + linked resources) |
| `POST /api/referrals/{task_id}/status` | Transition Task status (PATCH/PUT) |
| `GET/DELETE /api/logs`, `GET /api/logs/{id}` | API interaction log |
| `POST /api/outcome/parse` | Parse an OperationOutcome / response Bundle |

---

## Testing

```bash
cd pheref-portal
.\.venv\Scripts\python.exe -m pytest          # Windows
# or
pytest                                         # with venv activated
```

Tests cover the 20-entry Bundle structure (PUT/POST split, PSGC address extensions,
BP component decomposition, priority mapping, Task state, intra-bundle reference
integrity), the OperationOutcome parser, terminology fallback, page rendering, and the
config round-trip. They run fully offline (external calls are pointed at an unroutable
host so the curated fallbacks are exercised deterministically).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `pip install` fails building `pydantic-core` / `maturin` | Python 3.13/3.14 has no prebuilt wheel | Use Python 3.11 or 3.12 (`py -3.11 -m venv .venv`), or build via Docker |
| Header dot is **red** / `Test connection` fails | FHIR server unreachable, wrong URL, or proxy | Verify `FHIR Transactional Server URL` in `/admin`; check network/firewall; raise `HTTP timeout` |
| Dropdowns show a yellow **`fallback`** tag | Terminology/PSA server unreachable | Confirm Terminology/PSA URLs and token in `/admin`; codes still work via curated fallback |
| Submission returns parsed **error issues** | Profile/validation failure on the FHIR server | Open the issue list and **Developer Tools → API Log** to inspect the raw `OperationOutcome` |
| Task transition fails with "PATCH not supported" | Server lacks JSON-Patch | The portal auto-falls back to read-modify-write **PUT**; no action needed |
| Admin changes don't persist (Docker) | `config/` not mounted | Add `-v "$(pwd)/config:/app/config"` or use `docker compose` |
| Port 8000 already in use | Another process bound | Set `PHEREF_PORT` (venv) or change the published port in `docker-compose.yml` |
| PSA address lists only show the Kalibo locality | Live PSA API unreachable → fallback dataset | Configure a valid `PSA_TOKEN`/version in `/admin`; the curated set covers the Ana Reyes sample |

Use **Developer Tools → API Log** to inspect every FHIR/PSA request and response
(headers, timing, body) and the **OperationOutcome Parser** to translate server errors
into actionable messages.

---

## Project layout

```
pheref-portal/
├── app/
│   ├── main.py            # FastAPI app + static mount
│   ├── config.py          # layered settings (env + runtime overrides)
│   ├── fhir_client.py     # async FHIR client (logged)
│   ├── terminology.py     # ValueSet/$expand, $lookup (+ fallbacks)
│   ├── psa.py             # PSGC geography (+ fallback)
│   ├── bundle.py          # 20-entry transaction Bundle builder
│   ├── outcome.py         # OperationOutcome parser
│   ├── logstore.py        # in-memory API interaction log
│   ├── routers/           # api.py (JSON) + pages.py (HTML)
│   ├── templates/         # Jinja2 pages
│   └── static/            # css + js
├── tests/                 # pytest suite
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── run.py
```

---

> **Disclaimer:** The PH Core and PH eReferral IGs are draft versions under active
> development and are not intended for production use. Endpoints and profiles may change.
