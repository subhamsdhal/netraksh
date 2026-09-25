param(
    [string]$DatabasePath = "data/demo/sih_demo.db",
    [string]$AdminPassword = $env:SIH_DEMO_ADMIN_PASSWORD,
    [string]$OperatorPassword = $env:SIH_DEMO_OPERATOR_PASSWORD,
    [string]$AuditorPassword = $env:SIH_DEMO_AUDITOR_PASSWORD
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if ([string]::IsNullOrWhiteSpace($AdminPassword) -or
    [string]::IsNullOrWhiteSpace($OperatorPassword) -or
    [string]::IsNullOrWhiteSpace($AuditorPassword)) {
    throw "Set SIH_DEMO_ADMIN_PASSWORD, SIH_DEMO_OPERATOR_PASSWORD, and SIH_DEMO_AUDITOR_PASSWORD in the process environment."
}

$dbFull = [IO.Path]::GetFullPath($DatabasePath)
$dbDir = Split-Path -Parent $dbFull
New-Item -ItemType Directory -Force -Path $dbDir, (Join-Path $root 'data/archive') | Out-Null
if (Test-Path -LiteralPath $dbFull) {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    Copy-Item -LiteralPath $dbFull -Destination (Join-Path $root ("data/archive/sih_demo_pre_reset_" + $stamp + ".db"))
    Remove-Item -LiteralPath $dbFull -Force
}

$env:DATABASE_URL = "sqlite:///" + ($dbFull -replace '\\','/')
$env:ENV = "development"
$env:BOOTSTRAP_USERS = "true"
$env:SECRET_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$env:ADMIN_PASSWORD = $AdminPassword
$env:INITIAL_OPERATOR_PASSWORD = $OperatorPassword
$env:INITIAL_AUDITOR_PASSWORD = $AuditorPassword
$python = (Get-Command py -ErrorAction SilentlyContinue).Source
if ($python) {
    & $python -3.12 -m alembic upgrade head
    & $python -3.12 -c "from backend.database.session import SessionLocal,init_db; from backend.security.auth import bootstrap_users; from backend.main import _seed_demo_data; init_db(); db=SessionLocal(); bootstrap_users(db); _seed_demo_data(db); db.close()"
} else {
    $python = (Get-Command python -ErrorAction Stop).Source
    & $python -m alembic upgrade head
    & $python -c "from backend.database.session import SessionLocal,init_db; from backend.security.auth import bootstrap_users; from backend.main import _seed_demo_data; init_db(); db=SessionLocal(); bootstrap_users(db); _seed_demo_data(db); db.close()"
}
Write-Output ("SIH demo database ready: " + $dbFull)
