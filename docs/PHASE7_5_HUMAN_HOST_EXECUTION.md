# PHASE 7.5: HUMAN HOST EXECUTION GUIDE
**PROJECT**: NETRAKSH
**STATUS**: PENDING HUMAN EXECUTION

Because the AI tool session is structurally blocked from running persistent concurrent background tasks, true End-to-End local validation must be performed by a human operator on the Windows host. 

This document serves as the exact step-by-step procedure.

## 1. SECRET CONFIGURATION (BACKEND)
The NETRAKSH Backend enforces strict production secret validation. It will intentionally crash on startup if default passwords or missing secrets are detected.
For **isolated local testing only**, set the environment variable `ENV=development` to temporarily bypass production enforcement, OR supply secure overrides.

*In Terminal 1, run:*
```powershell
$env:ENV="development"
# OR, specify strong secrets if testing production configuration:
# $env:SECRET_KEY="<strong-random-key>"
# $env:ADMIN_PASSWORD="<strong-random-password>"
```
**CRITICAL**: Do NOT embed production credentials in scripts or your local environment.

## 2. CONCURRENT VALIDATION PROCEDURE

### TERMINAL 1: BACKEND API
Open a new PowerShell window in the repository root.
```powershell
$env:ENV="development"
.\scripts\start_backend.ps1
```
**Health Verification**:
Run the following in a separate PowerShell window to verify the Backend API is healthy:
```powershell
Invoke-WebRequest -Uri http://127.0.0.1:8000/docs
```
*Expected Outcome*: HTTP 200 OK.

### TERMINAL 2: FRONTEND DASHBOARD
Open a second PowerShell window in the repository root.
```powershell
.\scripts\start_frontend.ps1
```
**Health Verification**:
Open a web browser and navigate to `http://127.0.0.1:5173`.
*Expected Outcome*: The React dashboard loads and is able to hit the backend API without CORS errors.

### TERMINAL 3: EDGE PIPELINE
Open a third PowerShell window in the repository root. Ensure the Backend is already healthy.
```powershell
.\scripts\start_edge.ps1
```
**Health Verification**:
Monitor Terminal 3 output.
*Expected Outcome*: You should observe the video file opening (`demo/videos/vtest.avi`), frame processing, and successful initialization of the event pipeline to the backend.

## 3. SECURITY TESTS
With the backend running, execute these commands to verify security boundaries:
```powershell
# Unauthenticated API request
Invoke-WebRequest -Uri http://127.0.0.1:8000/api/v1/system/health -Method GET

# Invalid JWT test
Invoke-WebRequest -Uri http://127.0.0.1:8000/api/v1/auth/me -Headers @{Authorization="Bearer invalid_token"} -Method GET
```
*Expected Outcome*: Unauthorized requests should return `401 Unauthorized` or `403 Forbidden`.

## 4. GRACEFUL SHUTDOWN
To safely stop the deployment:
1. Go to Terminal 3 (Edge) and press `Ctrl+C`. Wait for exit.
2. Go to Terminal 2 (Frontend) and press `Ctrl+C`. Wait for exit.
3. Go to Terminal 1 (Backend) and press `Ctrl+C`. Wait for exit.

Do not aggressively kill the Python/Node processes from Task Manager unless they become completely unresponsive.

---

## HUMAN-EXECUTED EVIDENCE COLLECTION
*Operator: Execute the above steps and record your results below.*

- **Backend**: PENDING HUMAN EXECUTION
- **Frontend**: PENDING HUMAN EXECUTION
- **Edge**: PENDING HUMAN EXECUTION
- **Frontend → Backend**: PENDING HUMAN EXECUTION
- **Edge → Backend**: PENDING HUMAN EXECUTION
- **Database**: PENDING HUMAN EXECUTION
- **Evidence Storage**: PENDING HUMAN EXECUTION
- **Happy Path**: PENDING HUMAN EXECUTION
