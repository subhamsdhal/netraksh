@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
if not exist "%PYTHON%" set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%ROOT%\venv\Scripts\python.exe"
if not exist "%PYTHON%" for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_PATH set "PYTHON_PATH=%%P"
if not exist "%PYTHON%" if defined PYTHON_PATH set "PYTHON=%PYTHON_PATH%"
if not exist "%PYTHON%" if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
set "FRONTEND=%ROOT%\frontend"
set "VIDEO=%ROOT%\demo\videos\vtest.avi"
set "BACKEND_URL=http://127.0.0.1:8443"

echo ========================================================
echo  NETRAKSH local SIH demo launcher
echo ========================================================

if not exist "%PYTHON%" (
  echo ERROR: No usable Python interpreter was found.
  echo Run scripts\setup_windows.ps1, then retry.
  exit /b 1
)
"%PYTHON%" -c "import fastapi, cv2, ultralytics, uvicorn" >nul 2>&1
if errorlevel 1 (
  echo ERROR: The selected Python environment is incomplete: %PYTHON%
  echo Install backend and edge requirements, then retry.
  exit /b 1
)
if not exist "%FRONTEND%\package.json" (
  echo ERROR: Frontend package.json was not found.
  exit /b 1
)
if not exist "%VIDEO%" (
  echo ERROR: Bootstrap surveillance video was not found:
  echo        %VIDEO%
  exit /b 1
)
where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo ERROR: npm.cmd is not available on PATH.
  exit /b 1
)

echo [1/4] Backend       http://127.0.0.1:8443
start "NETRAKSH Backend" /D "%ROOT%" powershell.exe -NoExit -Command "$env:PYTHONPATH='%ROOT%'; & '%PYTHON%' -m uvicorn backend.main:app --host 127.0.0.1 --port 8443"

echo [2/4] Frontend      http://127.0.0.1:5173
start "NETRAKSH Frontend" /D "%FRONTEND%" powershell.exe -NoExit -Command "npm.cmd run dev -- --host 127.0.0.1 --port 5173"

echo Waiting briefly for the backend before starting edge workers...
timeout /t 5 /nobreak >nul

echo [3/4] Edge worker   cam-border-01
start "NETRAKSH Edge - cam-border-01" /D "%ROOT%" powershell.exe -NoExit -Command "$env:PYTHONPATH='%ROOT%'; $env:SYNC_INTERVAL_SECONDS='2'; $env:DEMO_LOOP_VIDEO='true'; & '%PYTHON%' edge\demo_runner.py --camera-id cam-border-01 --video-source '%VIDEO%' --backend-url '%BACKEND_URL%'"

echo [4/4] Edge worker   cam-checkpoint-01
start "NETRAKSH Edge - cam-checkpoint-01" /D "%ROOT%" powershell.exe -NoExit -Command "$env:PYTHONPATH='%ROOT%'; $env:SYNC_INTERVAL_SECONDS='2'; $env:DEMO_LOOP_VIDEO='true'; & '%PYTHON%' edge\demo_runner.py --camera-id cam-checkpoint-01 --video-source '%VIDEO%' --backend-url '%BACKEND_URL%'"

echo.
echo All four services were launched in separate windows.
echo Login:    http://127.0.0.1:5173/login
echo Backend:  http://127.0.0.1:8443
echo Smoke:    powershell -File scripts\demo_smoke.ps1
echo.
echo The workers use the repository's labelled demo surveillance clip until
echo Dashboard ADD VIDEO supplies a new real upload session. Close each named
echo service window to stop it; this launcher never kills unrelated processes.

endlocal
