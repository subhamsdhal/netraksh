param (
    [string]$HostIp = "127.0.0.1",
    [int]$Port = 8000
)

$PythonExe = "venv\Scripts\python.exe"

if (-Not (Test-Path $PythonExe)) {
    Write-Error "Virtual environment python.exe not found at $PythonExe. Please initialize the environment."
    exit 1
}

$env:PYTHONPATH = "."
Write-Output "Starting NETRAKSH Backend API on ${HostIp}:$Port..."
& $PythonExe -m uvicorn backend.main:app --host $HostIp --port $Port
