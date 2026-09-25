# PHASE 7.4: WINDOWS HOST DEPLOYMENT (MULTI-PROCESS)

## OVERVIEW
Because a single simulated/terminal tool session cannot natively sustain multiple concurrent foreground servers, true E2E execution must be run natively on the Windows host using separate, persistent processes.

This document describes how to execute the NETRAKSH E2E stack over `localhost`.

### REQUIRED TERMINALS
To run the full stack, you must open **three separate PowerShell windows**.

## 1. BACKEND API
Open **Terminal 1** in the repository root.

**Prerequisites**: A `.env` file must be present with strong production secrets (`SECRET_KEY`, `ADMIN_PASSWORD`, etc.), OR the environment must be set to `ENV=development`.

**Start Command**:
```powershell
.\scripts\start_backend.ps1
```
*Under the hood, this executes:*
`venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`

**Health Verification**:
Navigate to `http://127.0.0.1:8000/docs` to verify the API is serving.

## 2. FRONTEND DASHBOARD
Open **Terminal 2** in the repository root.

**Prerequisites**: Node.js v24+ must be installed. Dependencies must be installed via `npm install` within the `frontend/` directory.

**Start Command**:
```powershell
.\scripts\start_frontend.ps1
```
*Under the hood, this executes:*
`Set-Location frontend; npm run dev`

**Health Verification**:
Navigate to `http://127.0.0.1:5173` (or the port Vite provides) to access the dashboard.

## 3. EDGE INFERENCE PIPELINE
Open **Terminal 3** in the repository root.

**Prerequisites**: The Backend API must be running first.

**Start Command**:
```powershell
.\scripts\start_edge.ps1
```
*Under the hood, this executes:*
`venv\Scripts\python.exe edge/demo_runner.py --camera-id cam-border-01 --video-source demo/videos/vtest.avi --backend-url http://127.0.0.1:8000`

**Health Verification**:
Check Terminal 3 output for "Inference loop started" and monitor the Backend API terminal for incoming `/api/v1/events` POST requests.

## 4. SHUTDOWN & TROUBLESHOOTING
**Shutdown**:
Press `Ctrl+C` in all three terminals to gracefully terminate the processes.

**Troubleshooting**:
- **Pydantic ValidationError (Secrets)**: If the backend crashes on startup with `Production secrets not configured`, you must configure `.env` or run `$env:ENV="development"` before starting.
- **Port In Use**: Ensure ports 8000 and 5173 are free before starting.
- **Node Errors**: Ensure `npm install` was run in the `frontend` folder.
