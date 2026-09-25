# NETRAKSH Manual Windows Startup Runbook

This is a manual, native-Windows runbook for the SIH demonstration. Commands are intentionally explicit and are not executed by this task. Run each terminal from `D:\netraksh\netraksh`. Keep the backend, frontend, and two camera terminals open separately.

## A. First-time environment setup

```powershell
Set-Location D:\netraksh\netraksh
Get-Command py,python,node,npm -ErrorAction SilentlyContinue
py -0p
where.exe python
where.exe node
where.exe npm
```

Use Python 3.12 where available. Create a fresh environment; existing environments may reference an unavailable interpreter:

```powershell
Set-Location D:\netraksh\netraksh
py -3.12 -m venv .venv
& .\.venv\Scripts\Activate.ps1
python --version
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r .\requirements-backend.txt
python -m pip install -r .\requirements.txt
python -c "import cv2; print(cv2.__version__); print('cv2.face=', hasattr(cv2, 'face'))"
Set-Location .\frontend
npm ci
Set-Location ..
```

If `py -3.12` is unavailable, substitute the full `python.exe` path returned by discovery (for example `C:\Users\hp\AppData\Local\Programs\Python\Python312\python.exe`).

## B. Before every start

```powershell
Set-Location D:\netraksh\netraksh
& .\.venv\Scripts\Activate.ps1
$env:DATABASE_URL = 'sqlite:///D:/netraksh/netraksh/data/demo/sih_demo.db'
$env:ENV = 'development'
$env:PYTHONPATH = 'D:/netraksh/netraksh'
$env:BOOTSTRAP_USERS = 'false'
$env:VITE_BACKEND_URL = 'http://127.0.0.1:8443'
$env:VITE_WS_URL = 'ws://127.0.0.1:8443'
Test-Path D:\netraksh\netraksh\data\demo\sih_demo.db
Test-Path D:\netraksh\netraksh\data\archive\netraksh_pre_sih_demo_20260923_181037.db
Write-Host "NETRAKSH DEMO DATABASE: $env:DATABASE_URL"
```

For a newly reset database, set strong temporary `ADMIN_PASSWORD`, `INITIAL_OPERATOR_PASSWORD`, `INITIAL_AUDITOR_PASSWORD`, and `SECRET_KEY` values before starting. Never print or commit them.

## C. Backend (Terminal 1)

```powershell
Set-Location D:\netraksh\netraksh
& .\.venv\Scripts\Activate.ps1
$env:DATABASE_URL = 'sqlite:///D:/netraksh/netraksh/data/demo/sih_demo.db'; $env:ENV='development'; $env:PYTHONPATH='D:/netraksh/netraksh'; $env:BOOTSTRAP_USERS='false'
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8443
```

## D. Frontend (Terminal 2)

```powershell
Set-Location D:\netraksh\netraksh\frontend
$env:VITE_BACKEND_URL='http://127.0.0.1:8443'; $env:VITE_WS_URL='ws://127.0.0.1:8443'
npm run dev -- --host 127.0.0.1 --port 5173
```

## E. Camera 1 (Terminal 3)

```powershell
Set-Location D:\netraksh\netraksh
& .\.venv\Scripts\Activate.ps1
$env:PYTHONPATH='D:/netraksh/netraksh'; $env:SYNC_INTERVAL_SECONDS='2'; $env:DEMO_LOOP_VIDEO='true'
python edge\demo_runner.py --camera-id cam-border-01 --video-source demo\videos\vtest.avi --backend-url http://127.0.0.1:8443
```

## F. Camera 2 (Terminal 4)

```powershell
Set-Location D:\netraksh\netraksh
& .\.venv\Scripts\Activate.ps1
$env:PYTHONPATH='D:/netraksh/netraksh'; $env:SYNC_INTERVAL_SECONDS='2'; $env:DEMO_LOOP_VIDEO='true'
python edge\demo_runner.py --camera-id cam-checkpoint-01 --video-source demo\videos\vtest.avi --backend-url http://127.0.0.1:8443
```

## G. Health checks

```powershell
Invoke-WebRequest http://127.0.0.1:8443/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8443/ready -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8443/docs -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:5173/ -UseBasicParsing
```

## H. Smoke check

```powershell
Set-Location D:\netraksh\netraksh
powershell -ExecutionPolicy Bypass -File .\scripts\demo_smoke.ps1 -BackendUrl http://127.0.0.1:8443 -FrontendUrl http://127.0.0.1:5173
```

For authenticated checks, set `NETRAKSH_DEMO_USERNAME` and `NETRAKSH_DEMO_PASSWORD` in that terminal without displaying them.

## I. Optional tests

```powershell
Set-Location D:\netraksh\netraksh
& .\.venv\Scripts\python.exe -m pytest -q --basetemp artifacts\pytest-canonical-final-clean
Set-Location .\frontend; npm test -- --run; npm run lint; npm run build
```

## J. Read-only database checks

```powershell
& .\.venv\Scripts\python.exe -c "import sqlite3; p=r'D:\\netraksh\\netraksh\\data\\demo\\sih_demo.db'; db=sqlite3.connect(p); print('integrity=',db.execute('pragma integrity_check').fetchone()[0]); print('migration=',db.execute('select version_num from alembic_version').fetchone()[0]); print('events=',db.execute('select count(*) from events').fetchone()[0]); print('evidence=',db.execute('select count(*) from evidence_packages').fetchone()[0]); db.close()"
```

## K. Migration and process/port checks

```powershell
$env:DATABASE_URL='sqlite:///D:/netraksh/netraksh/data/demo/sih_demo.db'
python -m alembic current
python -m alembic heads
Get-NetTCPConnection -LocalPort 8443,5173 -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'netraksh|uvicorn|vite|edge|demo_runner' } | Select-Object ProcessId,Name,CommandLine
```

Expected Alembic head is `9d4e6b2f1a88`.

## L. Shutdown

Press `Ctrl+C` in camera 1, camera 2, frontend, then backend terminals. If a terminal is lost, identify the exact owner first:

```powershell
$p=(Get-NetTCPConnection -LocalPort 8443 -State Listen).OwningProcess
Get-Process -Id $p
Stop-Process -Id $p   # only after confirming the displayed process
```

Repeat with port `5173` if necessary. Do not use broad process-kill commands.

## M–O. Troubleshooting

Backend: confirm `python --version`, activated `.venv`, `DATABASE_URL`, port 8443, and `python -m alembic current`; inspect the uvicorn traceback.

Camera: confirm `demo\videos\vtest.avi` exists, `cv2.face` imports, backend health is green, and camera IDs are `cam-border-01` and `cam-checkpoint-01`.

Frontend: confirm `npm ci` completed, port 5173 is free, and `VITE_BACKEND_URL`/`VITE_WS_URL` point to 8443; inspect the Vite terminal and browser console.

## P. Manual browser check

Open `http://127.0.0.1:5173/`, sign in with the prepared demo account, then verify dashboard load, both camera tiles, live event/alert updates, evidence navigation, and audit navigation. Do not reset the database during an active demonstration.

## Optional destructive reset (not during an active demo)

```powershell
Set-Location D:\netraksh\netraksh
& .\scripts\reset_sih_demo.ps1 -AdminPassword '<new-strong-admin-password>' -OperatorPassword '<new-strong-operator-password>' -AuditorPassword '<new-strong-auditor-password>'
```

This archives the current demo DB and recreates only `data\demo\sih_demo.db`; it does not touch the forensic archive. Run only when a fresh demo database is explicitly required.
