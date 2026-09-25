param (
    [string]$CameraId = "cam-border-01",
    [string]$VideoSource = "demo/videos/vtest.avi",
    [string]$BackendUrl = "http://127.0.0.1:8000"
)

$PythonExe = "venv\Scripts\python.exe"

if (-Not (Test-Path $PythonExe)) {
    Write-Error "Virtual environment python.exe not found at $PythonExe. Please initialize the environment."
    exit 1
}

if (-Not (Test-Path $VideoSource)) {
    Write-Error "Video source $VideoSource not found."
    exit 1
}

$env:PYTHONPATH = "."
Write-Output "Starting NETRAKSH Edge Inference Node ($CameraId)..."
& $PythonExe edge/demo_runner.py --camera-id $CameraId --video-source $VideoSource --backend-url $BackendUrl
