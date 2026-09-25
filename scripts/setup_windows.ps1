param(
  [switch]$InstallDependencies
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$candidates = @(
  (Join-Path $Root '.venv\Scripts\python.exe'),
  (Join-Path $Root 'venv\Scripts\python.exe'),
  (Join-Path $env:LocalAppData 'Programs\Python\Python312\python.exe')
)
$python = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
  $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $python) { throw 'Python 3.12+ was not found. Install Python and rerun this script.' }

Write-Host "Using Python: $python"
& $python -c "import sys; print(sys.version); import fastapi, cv2, ultralytics; print('fastapi/cv2/ultralytics imports: OK'); print('cv2.face:', hasattr(cv2, 'face'))"
if ($LASTEXITCODE -ne 0) { throw 'The selected interpreter is missing required runtime packages.' }

if ($InstallDependencies) {
  & $python -m pip install -r (Join-Path $Root 'requirements-backend.txt')
  if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
  & $python -m pip install -r (Join-Path $Root 'requirements.txt')
  if ($LASTEXITCODE -ne 0) { throw 'Edge dependency installation failed.' }
}

Write-Host 'Windows runtime check complete.'
Write-Host 'Start the SIH demo with: .\start_netraksh.cmd'
