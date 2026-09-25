# NETRAKSH / SIH 26187 — Second complete live UI regression pass

Date: 2026-09-24  
Browser: Codex in-app browser  
Frontend: `http://127.0.0.1:5173`  
Backend: `http://127.0.0.1:8443`  
Database: `data/demo/sih_demo.db`

## Runtime

| Item | Result |
|---|---|
| `/health` / `/ready` | 200 / 200 |
| Frontend | 200 |
| WebSocket | Connected in Command Center |
| Camera 1 | ONLINE, live FPS/P/V/T and analyzed frame |
| Camera 2 | ONLINE, live FPS/P/V/T and analyzed frame |
| Database | Clean demo DB requested by the brief |

## Regression matrix

| Module | Route | Loads | Live data | Controls / navigation | Console / network | Status |
|---|---|---|---|---|---|---|
| Command Center | `/` | PASS | Both camera streams, sessions, frame IDs, P/V/T, events, reliability | Slot selectors, active camera, HUD, camera stop/restart, event filters | No new errors after hard refresh | PASS |
| System Health | `/camera-health` | PASS | Registered/active cameras, health and heartbeat state | Sector and attention filters, refresh | No new route error | PASS |
| Map Intelligence | `/map` | PASS | Honest 0-coordinate state | Zoom controls | No map crash | PASS |
| Alerts & Incidents | `/cross-command-alerts` | PASS | 105 live/persisted alerts | Severity/status filters, acknowledge/close controls | No unexpected request failure observed | PASS |
| Evidence Vault | `/evidence` | PASS | Event metadata, hash, signature state, decrypted image after bounded sync | Search/filter, event selection, verify, export | Transient evidence fetch now retries as SYNCING; no misleading immediate connectivity error | PASS |
| Face Watchlist | `/watchlist` | PASS | Honest empty state | Search, severity tabs, refresh, enrollment entry point | No error | PASS |
| Analytics | `/analytics` | PASS | Backend-derived counts, confidence, reliability, camera totals | Date presets, camera/event filters, refresh/export | No new React warning after reload | PASS |
| Audit Trail | `/audit` | PASS | Operator and system audit rows | Route navigation and row inspection | No error | PASS |
| Edge Performance | `/performance` | PASS | Locally measured prototype metrics disclosure | Route load | No blank/error state | PASS |
| Architecture | `/architecture` | PASS | Local chain and mock-ledger disclosure | Route load | No error | PASS |
| Camera Management | `/camera-management` | PASS | Existing camera rows and admin form | Route load, table inspection | No mutation performed | PASS |

## Controls and state checks

- Both HUD controls were toggled OFF/ON. The image remained live with telemetry while HUD text/overlays changed appropriately for each camera.
- Camera stop/restart was exercised. Single-camera mode showed `1 Active / 2 Registered` and `REQUIRES TWO ACTIVE CAMERA SOURCES`; restoring the slot returned both analyzed frames and dual mode.
- Dual mode retained independent camera sessions, frame indices and P/V/T values.
- Latest Events displayed live rows, camera identity, event type, severity, age and evidence links; the feed showed the latest 10.
- Reliability switched with camera scope and showed live Gate 1/2/3 values when a processed event was present.
- Empty states were explicit for watchlist, ANPR, map coordinates and unpopulated reliability rather than blank panels.
- Browser route navigation and a hard refresh were retested. Camera slot assignments now survive remount/refresh while the websocket inventory arrives asynchronously.

## Defects reproduced and fixed in this second pass

1. **Evidence Vault transient fetch error.** Under the live ingest load, the evidence image could briefly fail and immediately display “Could not reach the backend”. The loader now performs the same bounded retry window as HTTP 425 synchronization and shows `SYNCING EVIDENCE…`, ending in an honest timeout state if necessary. Browser retest reached `DECRYPTED EVIDENCE` with a real image.
2. **Demo slot assignments lost on remount/refresh.** Dashboard persisted the currently visible websocket subset; when one camera arrived first, it overwrote the saved two-slot assignment. Persistence now stores the operator’s assignments and does not reconcile them away while inventory is incomplete. Browser retest preserved both selected slots through route navigation and hard refresh.

Previously fixed defects (null corroboration crash, border shorthand warning, exact analyzed-frame cache/CORS) were also regression-tested; no new reproduction occurred after a hard refresh.

## Counts

- Modules discovered: 11
- Modules tested: 11
- Modules working: 11
- Modules partial: 0
- Modules broken: 0
- Controls tested: 40+ representative visible controls
- Controls working: all exercised controls
- Controls disabled with valid reason: export/refresh controls while their request was loading
- Dead controls: 0 observed
- Blank panels: 0
- Unexpected API errors: 0 observed after runtime startup
- Backend 500s: 0 observed in the browser pass
- New fatal console errors: 0 after hard refresh
- New React warnings: 0 after hard refresh
- WebSocket errors: 0 observed
- Frame/telemetry mismatches: 0 observed; both cards reported `ANALYZED FRAME · SAME SAMPLE`

## Remaining honest limitations

- CPU replay health is shown as `DEGRADED` at the current FPS.
- No real GPS coordinates are configured, so the map reports zero markers.
- The clean demo DB has no face-watchlist match or accepted plate read; the UI reports those empty states.
- Corroboration is temporal/spatial only and may honestly report `OUTSIDE TIME WINDOW`.
- The ledger is MOCK as disclosed by Architecture.
- Source replacement upload was not submitted because it would mutate the demo source; the visible entry point loaded and remained available.

## Final state

The backend, frontend, Camera 1 worker, Camera 2 worker and Codex browser were left running. The browser was returned to Command Center with both configured demo slots selected and both cameras online.

Screenshot evidence directory created at `artifacts/final_ui_browser_regression_pass2_20260924/`; browser screenshots were inspected during the live pass.

FINAL STATUS: WAITING FOR USER MANUAL VERIFICATION
