# SIH 26187 — Render Memory Limit Root-Cause Audit

Audit scope: diagnosis only. No application feature, deployment configuration, GitHub, Render service, database, or repository history was modified by this audit.

## Existing Render Configuration

The current `render.yaml` defines one Docker web service named `netraksh`, using `./backend/Dockerfile`, `plan: free`, and `/health` as its health check. It supplies `ENV=production`, a Render-managed `DATABASE_URL` environment value, and frontend CORS origins. The current Blueprint therefore describes a backend/control-plane service, not the historical monolithic image.

The current `backend/Dockerfile` copies only `backend/`, `shared/`, and Alembic files, installs `requirements-backend.txt`, and starts one Uvicorn process on `${PORT:-8000}`. It does not copy `edge/`, `demo/`, the frontend, or the edge model assets.

Important deployment correctness caveat: `backend/api/watchlist.py` unconditionally imports `cv2`, while `requirements-backend.txt` does not declare OpenCV. The local environment has OpenCV, so local startup can succeed, but a clean backend-only image may fail at import time. This is a startup/dependency defect, not an explanation for a memory OOM, and was not changed here.

## Compute Plan / Memory Limit

The repository declares `plan: free`, but the Render account was not authenticated in the read-only dashboard check. Consequently the effective RAM limit, service history, and billing/plan state are **not verified from Render**. No account-side RAM number is asserted in this report.

The historical measurements below are sufficient to compare the application footprint against any small free-tier limit, but they do not substitute for Render's actual limit or incident telemetry.

## Start Command

The historical root `Dockerfile` (the image used before `render.yaml` switched to `backend/Dockerfile` in commit `8c74e2a`) installed the full `requirements.txt`, copied edge code and model assets, and ran `start.sh`.

`start.sh` starts `python edge/demo_runner.py` in the background and then starts Uvicorn. An earlier historical image (`35f9ff7`) instead launched `mock_edge_simulator.py` in the background beside Uvicorn. Both are two-process service topologies; neither is backend-only.

The current backend image command is:

```text
uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

No Gunicorn, `--workers`, or other Uvicorn worker multiplier was found in the current or historical Render commands.

## Process Model

Evidence supports one Uvicorn process plus one background edge/simulator process in the historical monolithic Render service. The edge process creates inference components for each configured camera. There is no evidence of multiple Uvicorn workers being configured, so worker duplication is not the primary cause.

The current Blueprint's backend-only command has no edge subprocess, but the root `Dockerfile` remains a legacy monolithic compatibility image and must not be selected for the production service.

## Backend Imports

`backend.main` imports the API routers and backend services. The backend path imports NumPy and OpenCV through the watchlist/re-identification code, but it does not import `torch`, `torchvision`, `ultralytics`, `easyocr`, `onnxruntime`, or `retina-face` as part of the control-plane startup path. The backend-only RSS measurement was approximately 118 MiB after startup on the local host, with an initial jump of about 28 MiB and no continued growth over the short sample.

The OpenCV import caveat above remains a clean-image startup issue.

## AI Models Loaded

The edge path is materially heavier:

- YOLO/PyTorch detector: `DetectionTracker` constructs a YOLO runtime for each edge pipeline.
- EasyOCR: `ANPRModule` constructs an EasyOCR reader when available.
- ONNX: license-plate YuNet and optional SFace face recognition use ONNX Runtime/model state.
- OpenCV: frame decoding, preprocessing, LBPH/SFace support, and image operations.

Tracked model/media sizes are:

| Asset | Size on disk |
|---|---:|
| `yolov8n.pt` | 6.25 MiB |
| `face_recognition_sface_2021dec.onnx` | 36.90 MiB |
| `lpd_yunet.onnx` | 3.95 MiB |
| `demo/videos/uploaded_demo.mp4` | 50.73 MiB |

Disk size is not RAM size; model deserialization and runtime allocations are substantially larger.

## Edge Worker Behavior

Each edge pipeline initializes detector, ANPR, face/re-identification, evidence, and synchronization components. Two camera pipelines therefore duplicate substantial runtime/model state in one process. The local performance report measured CPU-only operation at approximately:

- One stream: RSS about 533 MiB to 703 MiB during model/runtime warm-up.
- Two streams: RSS about 609 MiB to 888 MiB.
- Four streams: approximately 1,198 MiB, characterized as stress-only and not stable.

The edge ingestion queue is bounded at depth 30 with drop-oldest behavior; telemetry queue depth is 2. VideoCapture is released on reconnect, stall, and reader shutdown.

## Dependency Footprint

The full `requirements.txt` used by the historical monolith includes `torch`, `torchvision`, `ultralytics`, `easyocr`, `onnxruntime`, OpenCV, RetinaFace-related dependencies, and the backend stack. The lightweight `requirements-backend.txt` intentionally omits these AI packages.

Disposable local import measurements (Windows process RSS; each is an independent process and therefore not additive) were:

| Import | RSS after import |
|---|---:|
| `numpy` | 33.7 MiB |
| `cv2` | 41.5 MiB |
| `onnxruntime` | 47.3 MiB |
| `torch` | 198.1 MiB |
| `ultralytics` | 240.3 MiB |
| `easyocr` | 303.5 MiB |

These figures explain why installing/importing the edge stack in a small web service is unsafe even before camera frames and model objects are fully active.

## Local Memory Measurements

The backend-only temporary process used the demo SQLite database and succeeded on `/health` and `/ready`. RSS was about 89.3 MiB at the first sample, rose to about 117.4 MiB within 0.5 seconds, and settled around 118.1 MiB by 9.5 seconds. Windows private-memory figures were not used as a Render/Linux RAM estimate.

The existing performance report explicitly states that its 1/2/4-stream measurements are short-run characterization, not a completed 10–15 minute leak test.

## Render Metrics

**Not verified.** The Render dashboard redirected to its login page in the read-only check. No service metrics, peak RSS, restart count, or incident timestamp were available without account authentication.

## Render Logs

**Not verified.** No Render OOM log or exit reason could be retrieved without dashboard authentication. The exact historical command and local measurements provide the root-cause evidence; they do not prove a particular Render incident timestamp.

## Root Cause

The most strongly supported root cause is the historical monolithic deployment combining the backend with one or more edge inference workloads:

1. The historical root image installed the full AI dependency stack.
2. Its startup command launched an edge worker/simulator in the same Render web service as Uvicorn.
3. The edge path initializes high-footprint PyTorch/YOLO, EasyOCR, OpenCV, and ONNX components.
4. Local CPU-only measurements reached about 703 MiB for one stream and 888 MiB for two streams, before any evidence that the process was leaking.

Therefore the likely OOM mechanism is **edge worker/model startup and two-camera runtime pressure inside a small Render web instance**, with the historical monolith as the enabling configuration. The account's exact RAM ceiling and Render's recorded OOM line remain unknown.

Contributing or alternative causes, ranked lower by evidence:

- **Multiple workers:** not supported; no worker multiplier was found.
- **Unbounded queues/cache:** not supported. Frame, telemetry, WebSocket, and re-identification caches are bounded or latest-value based. The demo upload state stores metadata by session and can grow over many uploads, but it is not the measured primary footprint.
- **Upload/ffmpeg buffering:** uploads are streamed in 1 MiB chunks to disk; `ffmpeg` uses `capture_output=True`, which can create a transient buffer, but this is not the sustained multi-camera footprint.
- **Traffic spike:** unknown because Render metrics were unavailable.
- **Memory leak:** not proven. Short-run RSS rises during initialization/workload, and the existing report did not complete a long leak test.

## Leak Assessment

No leak conclusion is justified from the available evidence. The application has bounded capture queues, bounded WebSocket client queues, latest-per-camera telemetry state, and a re-identification cache capped at 5,000 entries with TTL. A controlled 10–15 minute backend-only and edge-worker soak test with RSS samples would be required to distinguish a true monotonic leak from model warm-up and workload growth.

## Recommended Deployment Split

Use the documented Edge/Central split:

- Render web service: backend/control plane only, one Uvicorn process, managed Postgres, no `edge/`, no Torch/YOLO/EasyOCR, and no camera inference.
- Camera-side edge device/container: camera ingestion, inference, evidence staging, and offline queue; one explicitly bounded pipeline per camera or a deliberately sized worker pool.
- Frontend: static hosting (Firebase Hosting or Vercel), built with `npm run build`; do not run Vite's development server in the Render backend service.

This split removes the high-memory model lifetime from the web service and makes edge capacity independently measurable.

## Backend-Only Render Requirements

Before any future deployment (not performed here):

1. Keep `render.yaml` pinned to `./backend/Dockerfile`; do not select the legacy root `Dockerfile`.
2. Ensure the backend image declares every unconditional backend import, especially OpenCV or a code path that does not require it.
3. Supply a real managed PostgreSQL `DATABASE_URL` through Render's secret environment, not SQLite on ephemeral service storage.
4. Supply strong generated production secrets and confirm `/health` and `/ready` after deployment.
5. If account metrics show the backend-only service itself approaching its limit, capture those metrics before changing plan or process settings.

## Frontend Deployment

The frontend package provides `npm run build` and produces a static `dist` bundle. The current backend Dockerfile does not copy or serve the frontend. Host that bundle on Firebase/Vercel (the origins already present in `render.yaml`) or use a separate static service. No frontend deployment was performed in this audit.

## GitHub Repository Hygiene

No GitHub changes were made. The worktree was not reset, cleaned, committed, or pushed.

Current tracked-file checks found no tracked real `.env`, database, PEM, private-key, or P12 file. Runtime/generated directories are generally ignored, but tracked large/demo assets remain listed above.

Historical `render.yaml` commits contain a hardcoded database credential that the current file says was revoked. This means a Git history rewrite is required **only if the repository is to be treated as clean/publicly safe after the historical secret exposure**. Rotation/revocation and any history rewrite are separate authorized operations and were not performed.

## Secrets Check

Current source contains development-only weak-default and placeholder literals in configuration/tests, as expected for local validation; production configuration rejects those defaults. No current tracked live secret file was found. The historical database credential exposure in Git history is the material secret finding; its value is intentionally not reproduced in this report.

## Large Files

Tracked model/video assets total roughly 98 MiB across the files listed in the model table. These are not themselves proof of RAM exhaustion, but the edge model files cause runtime allocations far above their on-disk sizes. The full edge dependency image is also materially larger than the backend-only image.

## Pre-Push Changes Required

No changes are required or authorized as part of this diagnosis. Before a future production push/deploy, the owner should separately authorize and review:

- the backend-only OpenCV dependency/startup correction;
- a clean Render service configuration check confirming `backend/Dockerfile`;
- secret rotation and, if desired, a coordinated Git history cleanup for the revoked historical database credential;
- a long-duration memory soak test for the edge runtime.

Those actions were deliberately not performed here.

