if (-Not (Test-Path "frontend\package.json")) {
    Write-Error "Frontend directory or package.json not found. Run this from the repository root."
    exit 1
}

Write-Output "Starting NETRAKSH Frontend Node API..."
Set-Location frontend
npm run dev
