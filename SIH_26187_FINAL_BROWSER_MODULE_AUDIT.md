# NETRAKSH / SIH 26187
## Final live UI module-by-module browser audit

Audit date: 2026-09-24  
Browser: Codex in-app browser, `http://127.0.0.1:5173/`  
Backend: `http://127.0.0.1:8443`  
Database: `data/demo/sih_demo.db`  
Operator: `admin` (ADMIN)

## Runtime acceptance

| Check | Result | Evidence |
|---|---|---|
| Backend health/readiness | PASS | `/health` and `/ready` returned 200 during the live run |
| Frontend | PASS | Vite served 5173 and all routes rendered |
| Edge pipelines | PASS | `cam-border-01` and `cam-checkpoint-01` continuously posted telemetry, frames and events |
| Camera 1 / Camera 2 | PASS | Both cards showed ONLINE, live FPS, persons, vehicles, tracks and analyzed-frame images |
| Camera recovery | PASS | Stopped Camera 2 in the UI; Camera 1 stayed live and the second slot recovered after re-selection |
| Dual-camera state | PASS | Final state showed 2 Active / 2 Registered; corroboration panel honestly reported `OUTSIDE TIME WINDOW` when no match existed |
| Auth/RBAC | PASS | Invalid login displayed an error; admin login, logout and protected routes worked |

## Visible module audit

| Module / route | Controls exercised | Live result | Status |
|---|---|---|---|
| Command Center `/` | Active-camera selector, slot selectors, HUD, event camera scope, reliability scope, camera STOP/restart | Both demo sources rendered analyzed frames and live P/V/T; reliability pipeline populated real factors; no fabricated corroboration | PASS |
| System Health `/camera-health` | All Sectors, Needs Attention, refresh | Two registered cameras loaded with health/FPS and degraded-state explanation; filters changed the list | PASS |
| Map Intelligence `/map` | Zoom in/out | Honest empty-map state: `NO GEOLOCATION CONFIGURED`; zoom controls remained usable | PASS |
| Alerts & Incidents `/cross-command-alerts` | Severity/status filters, Acknowledge, Close, reload | Event changed to ACK then CLOSED and persisted after reload | PASS |
| Evidence Vault `/evidence` | Search, decision/type/stream filters, export control, event selection, Verify | Latest event loaded a decrypted evidence frame and hash details; missing/old entries use honest no-evidence states | PASS |
| Face Watchlist `/watchlist` | Search, severity filters, Refresh, enroll entry point | Empty watchlist was clearly reported; controls remained functional | PASS |
| Analytics `/analytics` | 6-hour range, camera filter, refresh, export entry point | Real event totals/reliability/confidence updated to the selected camera and range | PASS |
| Audit Trail `/audit` | Route load and log inspection | Append-only entries showed login, alert actions and edge key bootstrap history | PASS |
| Edge Performance `/performance` | Route load | CPU prototype metrics page disclosed locally measured metrics and loaded without a blank/error state | PASS |
| Architecture `/architecture` | Route load | Local chain, Ed25519 and mock-ledger limitations were explicitly disclosed | PASS |
| Camera Management `/camera-management` | Route load, camera table and provisioning controls | Existing two camera rows and admin provisioning form rendered without mutation | PASS |

## Reproducible defects fixed during this audit

1. **Dashboard crash when the corroboration API returned `null`.** The cross-camera panel read `latestEvent.corroboration_distance_m` without guarding `latestEvent`. The render now uses optional chaining and supports the correlation response distance. Retest: dual-camera Command Center rendered normally and showed `NOT CORROBORATED · OUTSIDE TIME WINDOW`.
2. **React style conflict warning.** Analytics, Alerts and Health filter buttons mixed `border` shorthand with `borderColor`. They now use explicit `borderStyle`/`borderWidth`; no new warning appeared after retesting those controls.
3. **Exact analyzed-frame browser path.** The bounded frame cache was widened for WebSocket batching and the custom frame headers were exposed through CORS. Retest: both camera cards displayed `Latest analyzed frame` with same-sample HUD telemetry.

## Remaining honest demo limitations

- Health is `DEGRADED` because the CPU replay FPS is below the nominal target; this is shown rather than hidden.
- Map markers are unavailable until real camera coordinates are registered.
- Watchlist, ANPR and face results are empty for this clean demo database; the UI says so instead of inventing matches.
- Cross-camera corroboration is temporal/spatial only. The final live sample was correctly reported as outside the configured time window, not as a match.
- The permissioned ledger is explicitly MOCK in the Architecture page.

## Final browser state

All services and the Codex browser were left running. The browser was returned to Command Center with both slots assigned to `cam-border-01` and `cam-checkpoint-01`, both ONLINE, and the active camera selector on the live dual-camera scope.

**Audit totals:** 11 visible modules checked, 3 reproducible defects fixed, 0 unresolved browser-rendering defects observed after retest.
