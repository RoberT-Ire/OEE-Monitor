# Plant Monitor — V2.0

A development prototype for a building-based, read-only manufacturing monitoring service. FastAPI + SQLAlchemy + HTML/CSS/JavaScript. No Node.js, frontend build step, internet assets or external chart libraries are required. Light theme by default, with a saved dark-theme preference.

## Run locally (Windows)

Extract the archive and open the `plant-monitor-v2` folder in IntelliJ, VS Code or a terminal. Python 3.11 or newer recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

Open http://localhost:8000 in your browser. API documentation: http://localhost:8000/docs (demo only). On macOS/Linux use `.venv/bin/python` instead of the Windows path. Stop the service with Ctrl+C.

The default mode automatically creates a local `demo-v2.db` SQLite database and seeds 12 illustrative machines, five illustrative building groups, 30 days of daily production records and 24 hours of sensor readings. Demo readings refresh every 10 seconds. The daily production figures and loss reasons are simulated historical records, not calculated from the simulated sensor feed. Demo startup resets the demo readings and records; no connection to company systems is made. Do not use the demo database for important data. The previous V1 `demo.db` is separate and untouched.

### Accounts

| Role | Username | Password | Demo scope |
|---|---|---|---|
| Engineer | engineer | demo-engineer | All 12 machines, all buildings, reports, CSV and all sensor fields |
| Operator | operator | demo-operator | Three Large Liquid machines, basic performance and production rate, no engineering sensor fields or reporting endpoint |

The demo sign-in buttons fill in the credentials automatically. Both roles are read-only. Do not expose demo accounts outside a local development environment.

## Interface

- Overview: overall OEE, running count, output, recorded downtime, OEE trend and machine status summary.
- Buildings: selectable building summary cards and building-filtered dashboards.
- Machines: search by name, ID or building; filter by live state; open an individual machine.
- Machine detail: OEE components, latest readings, 1/6/12/24-hour sensor chart, recorded downtime reasons and recent observed transitions. Raw engineering sensors are restricted server-side.
- Reports (engineer, supervisor, admin): daily trends, building comparison, recorded loss reasons, machine table, CSV export.
- Alerts: current stopped, warning, unknown or missing-data states. Not a validated safety alarm system.
- All views support the shared building selector and 1/7/30-day reporting period. The theme switch is in the top bar. Auto-refresh is paused while the tab is hidden or a filter is being edited.

The building names and machine groupings are illustrative, not verified site assignments. Status values are placeholders and include Running, Warning, Stopped, Not scheduled, No recent data and Unknown. No recent data is not a confirmed shutdown. Warnings are illustrative, not configured industrial safety thresholds.

## OEE calculations

Daily production records hold planned minutes, run minutes, total units, good units and ideal units per minute. The API calculates:

- Availability = run time / planned production time.
- Performance = ideal total production time / run time.
- Quality = ideal good production time / ideal total production time. For a single fixed-rate machine this equals good units / total units. For multiple machines this is weighted by ideal production time rather than mixing unlike product counts.
- OEE = availability × performance × quality = ideal good production time / planned production time.

Aggregate OEE is weighted by planned production time. Unscheduled (zero planned time) or invalid records are excluded. Missing denominators produce null, displayed as a dash. Recorded output is a mixed-product count and not a comparable physical volume. Recorded downtime = planned minus run time, distinct from observed stopped minutes in sensor history. Observed metrics exclude excessive gaps and non-operational states; warnings count as operating time in the demo. All data timestamps and reporting days use UTC. The gauges use illustrative display bands, not approved targets. Verify shift boundaries, product-specific ideal rates, planned breaks, quality definitions, data coverage and KPI methodology with stakeholders before deployment.

## MySQL integration

`schema.sql` describes the five tables expected by the SQLAlchemy models. The default demo uses SQLite for a zero-configuration start. The same SQLAlchemy queries support MySQL via PyMySQL. An optional `sample_data.sql` contains illustrative rows for a NEW empty MySQL development database. Its sensor timestamps are fixed at export time, so the live state will become stale; this is expected. Never import into an existing production database.

To prepare an approved non-demo development database:

1. Ask the database owner to create a dedicated empty database and review `schema.sql`. Import it, then optionally import `sample_data.sql` into that empty database. For actual integration, have the database owner map existing tables or approved read-only views to the model in `app/database.py` instead.
2. Create a dedicated application DB account with SELECT access only to the relevant tables/views. Do not use a root account.
3. Copy `.env.example` to `.env`; set `MONITOR_DEMO=false`, a `mysql+pymysql://...` URL, and a unique random session secret (generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Set `MONITOR_SAMPLE_DATA=true` if using the optional sample SQL so the interface remains labelled as illustrative. Never commit credentials.
4. Run `python -m tools.create_user` using the virtual environment. Enter a role and authorised machine IDs (or `*` for all). No demo accounts are enabled in non-demo mode.
5. Start the app. `MONITOR_SECURE_COOKIE=true` requires HTTPS. Only for isolated localhost HTTP testing, set `MONITOR_SECURE_COOKIE=false`; never do this for a deployed service. Use a company-approved HTTPS reverse proxy, authenticated access and read-only network rules for any real deployment.

Production mode never creates tables, seeds or writes readings. The app itself does not control machines or send commands. The actual company database schema and security architecture have not been tested. Local signed-cookie sessions, in-memory login rate limiting, and file-based accounts are prototype controls; replace with approved enterprise authentication, session revocation, centrally managed permissions, audit logging and deployment hardening. Do not use this prototype as a safety or regulated production decision system without formal validation.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Eight automated tests cover authentication, machine permissions, overview aggregation, building filtering, reporting access, engineering sensor restrictions, history and logout. Browser UI smoke-tested with Chromium using a local test harness bridged to FastAPI's TestClient because direct browser navigation to localhost was blocked in the build environment. MySQL connection was not tested here.

## Key files

- `app/main.py`: authentication, permission checks, API routes, OEE calculations.
- `app/database.py`: SQLAlchemy models and connection factory.
- `app/config.py`: configuration, account handling and password hashing.
- `app/demo.py`: simulated data and periodic refresh.
- `app/static/`: frontend HTML, styling and JavaScript.
- `schema.sql`, `sample_data.sql`: reference MySQL schema and optional illustrative records.
- `tools/create_user.py`: local account creation.
- `tests/test_api.py`: API regression tests.
