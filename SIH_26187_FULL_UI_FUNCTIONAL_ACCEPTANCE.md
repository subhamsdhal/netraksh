# NETRAKSH / SIH 26187 — Full UI Functional Acceptance

**Date:** 2026-09-23  
**Baseline:** `main` at `8a73299`  
**Runtime:** native Windows, backend `127.0.0.1:8443`, frontend `127.0.0.1:5173`

## Decision

All 11 visible sidebar routes were opened in the live browser and assigned a final status. Eight are verified working, two have verified honest empty states, and Evidence Vault is partial because one sampled recent record had a valid SHA-256 and Ed25519 signature but a broken predecessor chain. No route is unknown, no unexplained blank panel remains, and no dead judge-facing control was found.

## Runtime

| Component | Live evidence | Result |
|---|---|---|
| Backend | `/ready` 200; controlled restart recovered | PASS |
| Frontend | SPA navigation and direct reload on major routes | PASS |
| Camera 1 | `cam-border-01`, live telemetry/events | PASS |
| Camera 2 | `cam-checkpoint-01`, live telemetry/events; paused-session recovery proven | PASS |
| Database | real events, alerts, evidence, audit and analytics loaded | PASS |
| WebSocket | connected; telemetry/events recovered after backend restart | PASS |

## Sidebar matrix

| Module | Route | Role | Live data | Controls tested | Result | Remaining issue |
|---|---|---|---|---|---|---|
| Command Center | `/` | authenticated | REST + WS + two workers | camera/source selects, Add/Replace, Start, Stop, event/ANPR/reliability filters, links | VERIFIED WORKING | CPU bounded; honest ANPR no-read |
| System Health | `/camera-health` | authenticated | camera health and metrics | rows, freshness, reload | VERIFIED WORKING | historical test nodes remain registered but not active dashboard sources |
| Map Intelligence | `/map` | authenticated | shared camera registry | load, zoom, reload | VERIFIED WORKING WITH HONEST EMPTY STATE | no camera coordinates configured |
| Alerts & Incidents | `/cross-command-alerts` | authenticated | real alerts/status | severity/status filters, list, acknowledge surface, map, reload | VERIFIED WORKING | high-volume list is bounded by existing limit |
| Evidence Vault | `/evidence` | authenticated | real evidence/media | search, filters, open, image, metadata, verify, export surface | PARTIAL | sampled live predecessor chain BROKEN |
| Face Watchlist | `/watchlist` | role-aware | real watchlist API | empty state, tabs, search, refresh, enrollment open/close | VERIFIED WORKING WITH HONEST EMPTY STATE | no consented face fixture |
| Analytics | `/analytics` | authenticated | five database aggregates | presets, date inputs, camera/type filters, refresh, CSV, charts | VERIFIED WORKING | uptime correctly redirects to Performance |
| Audit Trail | `/audit` | admin/auditor | real audit rows | filters, dates, refresh/reload, rows | VERIFIED WORKING | no user-management sidebar route |
| Edge Performance | `/performance` | authenticated | real edge metrics | camera selection, cards, refresh/reload | VERIFIED WORKING | CPU-only throughput is disclosed |
| Architecture | `/architecture` | authenticated | explanatory | route/reload and stage content | VERIFIED WORKING | Fabric remains mock adapter |
| Camera Mgmt | `/camera-management` | ADMIN | registry and health | list, location editor, coordinate inputs, provision form | VERIFIED WORKING | no destructive control exposed |

## Function/control matrix

Repeated row actions are counted once by control type.

| Module | Function/control | Browser tested | Backend verified | Result |
|---|---|---:|---:|---|
| Global | 11 sidebar links, active route and deep-link reload | Yes | Yes | PASS |
| Global | status strip, alerts link, account display, Sync and Demo controls | Yes | Yes | PASS |
| Dashboard | active camera and two slot selectors | Yes | Yes | PASS |
| Dashboard | Add/Replace, Start/Analyze and Stop | Yes | Yes | PASS |
| Dashboard | single/dual scope, telemetry, latest event and freshness | Yes | Yes | PASS |
| Dashboard | event ALL/CAM1/CAM2 filters, latest-10 and evidence links | Yes | Yes | PASS |
| Dashboard | ANPR filters/no-read state | Yes | Yes | PASS |
| Dashboard | reliability selector/three gates | Yes | Yes | PASS |
| Dashboard | correlation one/two-camera states and details | Yes | Yes | PASS |
| Health | fleet rows, health, FPS and freshness | Yes | Yes | PASS |
| Map | zoom and no-geolocation state | Yes | Yes | PASS |
| Alerts | severity/status filters, list and acknowledge lifecycle | Yes | Yes | PASS |
| Evidence | search, decision/type/stream filters and record open | Yes | Yes | PASS |
| Evidence | protected image, metadata and integrity verification | Yes | Yes | PARTIAL — chain finding |
| Evidence | Export Ledger CSV surface | Yes | Yes | PASS |
| Watchlist | search, tabs, refresh and enrollment form open/close | Yes | Yes | PASS |
| Watchlist | required fields, threat selector and image chooser | Yes | Yes | PASS |
| Watchlist | enrollment submit | Not submitted | Yes | NOT APPLICABLE — no safe face fixture |
| Analytics | presets, custom dates, camera/type filters and refresh | Yes | Yes | PASS |
| Analytics | CSV enablement and all stats/charts/tables | Yes | Yes | PASS |
| Audit | user/action/date controls and rows | Yes | Yes | PASS |
| Performance | camera selector and live metric cards | Yes | Yes | PASS |
| Architecture | stages and performance reference | Yes | N/A | PASS |
| Camera Mgmt | list, Set Location editor and Save surface | Yes | Yes | PASS |
| Camera Mgmt | provision fields and validation surface | Yes | Yes | PASS |

**Control count:** 54 visible control types tested/inspected; 52 working; 2 intentionally not submitted/destructive due absent safe fixture; 0 dead controls.

## API / WS matrix

| Module | REST | WS | Result |
|---|---|---|---|
| Dashboard | `/events`, `/cameras`, `/system/*`, `/api/dashboard/video/*`, `/correlation/current` | event, health, metrics, telemetry, correlation | PASS |
| Health / Map | `/cameras`, health/system endpoints | health, metrics, telemetry | PASS / honest empty map |
| Alerts | `/alerts`, lifecycle endpoints, `/system/status` | event/alert updates | PASS |
| Evidence | event detail, protected media and verify endpoints | event updates | PARTIAL — data chain finding |
| Watchlist | `/watchlist` and enrollment/sync endpoints | N/A | PASS — empty |
| Analytics | summary, timeseries, by-type, by-camera, by-severity, options | targeted refresh event | PASS |
| Audit | `/audit` | N/A | PASS |
| Performance | `/system/metrics` | metrics | PASS |
| Camera Mgmt | `/cameras`, `/cameras/{id}/location` | health | PASS |

## Root causes fixed

### Camera 2 unrecoverable after reload

- **Symptom:** a server-side paused scoped session remained, but lost browser storage removed the Start button.
- **Root cause:** `video/current` exposed only global state and Dashboard restored only that state.
- **Fix:** `video/current?camera_id=...` now returns only the selected camera's scoped session; Dashboard restores each visible slot.
- **Live retest:** a controlled Camera 2 session was paused, the page reloaded, `START / ANALYZE` reappeared, and clicking it restored ONLINE telemetry/FPS/tracks/events.

### Analytics transient `Failed to fetch`

- **Symptom:** initial or filtered aggregate load could fail although endpoints returned 200.
- **Root cause:** development StrictMode produced near-identical timestamp keys and duplicate batches; response bodies remained unread until the batch ended.
- **Fix:** stable five-second request keys, sequential body consumption, in-flight reuse and bounded transport retry.
- **Live retest:** complete analytics rendered; `cam-border-01` returned 5,299 real events, one active camera and enabled charts/CSV.

### Map error instead of empty state

- **Symptom:** `Unable to load camera locations` while Camera Management loaded the registry.
- **Root cause:** Map duplicated the realtime hook's camera request and hit the same local request collision.
- **Fix:** Map uses the hook's authoritative registry.
- **Live retest:** explicit `NO GEOLOCATION CONFIGURED` state renders.

### Stale architecture latency

- **Symptom:** a hardcoded `~165–175 ms/frame` contradicted measured CPU performance.
- **Fix:** replaced with `LIVE · SEE EDGE PERFORMANCE`.
- **Live retest:** corrected live page wording verified.

## Final browser error summary

| Signal | Count |
|---|---:|
| Fatal console errors | 0 |
| Failed API calls after fixes | 0 |
| Unexpected API 4xx | 0 |
| Backend 500 | 0 |
| WebSocket errors | 0 |
| Dead buttons | 0 |
| Blank/unexplained panels | 0 |
| Stale-value defects | 0 |

Transient fetch failures during the controlled backend restart were investigated and are not final steady-state failures.

## Automated validation

- Focused backend dashboard/correlation tests: **26 passed**.
- Frontend: **13 passed in 6 files**.
- Frontend lint: **exit 0**, warnings only.
- Frontend production build: **PASS**, 2,437 modules transformed.
- Canonical Python suite: **689 passed, 11 skipped, 1 deselected**; two library deprecation warnings and two shutdown-only unawaited-coroutine warnings remain non-failing.

## Honest limits / external blocks

- Docker/PostgreSQL/MinIO execution is blocked by unavailable Docker tooling.
- No live RTSP server, physical CCTV or browser live-transport fixture exists.
- Repository clip: honest `No plate read`; no ANPR accuracy claim.
- No consented face fixture; no face accuracy claim.
- No labeled real-night dataset; only functional/synthetic validation.
- Fabric uses the mock adapter.
- CPU-only throughput is suitable for the bounded demo, not a scalability claim.
- One sampled current evidence package had valid hash/signature but a broken predecessor chain; use a preverified record or disclose this when showing continuity.

## Totals

- Sidebar modules discovered: **11**
- Verified working: **8**
- Working with honest empty state: **2**
- Partial: **1**
- Broken: **0**
- Unknown: **0**
