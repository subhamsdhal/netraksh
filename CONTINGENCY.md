# Live Judging Contingency Plan

This document outlines fallback commands and troubleshooting steps to ensure the NETRAKSH demo can be presented smoothly, even if network or hardware issues arise during live judging.

## 1. Quick Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `start_netraksh.cmd` fails or flashes and closes | Hardcoded Python path issue | Open the `.cmd` file and ensure `set PYTHON=python` resolves correctly, or set it to the absolute path of `python.exe` on your machine. |
| Edge pipelines crash on startup | Missing dependencies / YOLO download failure | Ensure `pip install -r requirements.txt` was run. If offline, YOLOv8n weights (`yolov8n.pt`) must be cached in the working directory or `~/.config/Ultralytics`. |
| Dashboard shows no events | Backend race condition | The edge pipelines might have started polling before the backend was fully up. Press any key in the `start_netraksh.cmd` window to kill all processes, then run it again. |
| Port `8443` error | Port conflict | Another service (or a previous un-killed NETRAKSH backend) is using port 8443. Run `taskkill /F /IM python.exe` and retry. |

## 2. Manual Fallback Commands

If `start_netraksh.cmd` completely fails due to environment restrictions (e.g., CMD scripts blocked), run these commands manually in three separate console windows from the repo root:

**Terminal 1 (Backend + UI):**
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8443
```
*Wait for "Application startup complete", then proceed to Terminal 2.*

**Terminal 2 (Camera 1):**
```bash
python edge/demo_runner.py --camera-id cam-border-01 --video-source demo/videos/vtest.avi --backend-url http://localhost:8443
```
*Wait 15 seconds to establish realistic temporal separation, then proceed to Terminal 3.*

**Terminal 3 (Camera 2):**
```bash
python edge/demo_runner.py --camera-id cam-checkpoint-01 --video-source demo/videos/vtest.avi --backend-url http://localhost:8443
```

## 3. Screen Recording Backup

It is **highly recommended** to have a pre-recorded video of the full Steps 1–9 walkthrough (as documented in `walkthrough.md`) available on the presentation laptop.
This ensures that if the venue has strict network blocking, no Wi-Fi, or restrictive permissions that prevent Python/SQLite execution, the evaluator can still see the exact E2E flow and UI capabilities exactly as they were implemented.
