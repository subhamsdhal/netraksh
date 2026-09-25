# SIH 26187 — Local video Add/Replace validation

Date: 2026-09-24  
Browser: Codex in-app browser  
Database: `data/demo/sih_demo.db`

## Root cause

Two independent defects were reproduced:

1. `Dashboard.jsx` rejected valid local containers when Windows supplied an empty/generic MIME type. Validation now accepts a conservative video-extension allowlist and still leaves content/size validation to the authenticated backend.
2. `edge/demo_runner.py` intentionally nulled browser-uploaded source/session values whenever `DEMO_LOOP_VIDEO=true`. The UI could therefore display the uploaded name while the worker continued the CLI replay. The worker now honors an explicit browser source/session and restarts the pipeline on a source/session change.

The STOP action also discarded the selected source metadata. It now keeps the source bound to the slot in `PAUSED` state so START/ANALYZE restarts the same selected source.

## Browser acceptance

| Flow | Result |
|---|---|
| Camera 1 Add Video → `vtest.avi` | PASS — picker opened, upload accepted, source label updated, AVI correctly reported as no native preview, analyzed-frame path populated |
| Camera 1 Start | PASS — frame HUD session changed to the uploaded session prefix `7700723f` |
| Camera 2 Add Video → `vtest.avi` | PASS — independent source/session `1ea3fa9b` and analyzed frame |
| Same-file reselection | PASS — a new upload/source label was created on selecting the same file again |
| Stop then restart | PASS — selected source remained attached and START/ANALYZE reappeared |
| Camera 1 replacement with `vtest.mp4` | PASS — new source label `uploaded_7f8679f8...mp4`; after Start, analyzed HUD session `7f8679f8` matched the replacement source |
| Invalid extension | Validation path retained; no backend upload was issued by the extension/MIME guard |
| Cancel picker | No source mutation observed when picker was not committed |
| Camera slot targeting | PASS — Camera 1 and Camera 2 showed separate source labels/session prefixes |
| AVI browser preview | Honest limitation — native Chromium preview is unavailable without ffmpeg; UI shows actionable message and uses authoritative analyzed-frame preview |

## Verification

- Backend `/health` and `/ready`: 200.
- Frontend build: PASS (`npm run build`).
- Final browser state: Command Center open, both workers running, Camera 1 on the replacement MP4 analyzed session; Camera 2 worker running.

## Remaining local-video limitation

AVI files are accepted and processed by the edge worker, but cannot be shown in a Chromium native `<video>` preview on this host because ffmpeg is unavailable. The UI explicitly distinguishes this from upload failure and displays the analyzed-frame preview instead.

FINAL STATUS: WAITING FOR USER MANUAL VERIFICATION
