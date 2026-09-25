param(
    [string]$BackendUrl = "http://127.0.0.1:8443",
    [string]$FrontendUrl = "http://127.0.0.1:5173"
)

$ErrorActionPreference = "Stop"
$failures = [System.Collections.Generic.List[string]]::new()

function Test-Http {
    param([string]$Name, [string]$Uri, [hashtable]$Headers = @{})
    try {
        $response = Invoke-WebRequest -Uri $Uri -Headers $Headers -UseBasicParsing -TimeoutSec 10
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
            throw "HTTP $($response.StatusCode)"
        }
        Write-Host "PASS  $Name ($($response.StatusCode))" -ForegroundColor Green
        return $response
    } catch {
        $failures.Add("${Name}: $($_.Exception.Message)")
        Write-Host "FAIL  $Name" -ForegroundColor Red
        return $null
    }
}

Test-Http "frontend" "$FrontendUrl/" | Out-Null
Test-Http "backend health" "$BackendUrl/health" | Out-Null
Test-Http "backend ready" "$BackendUrl/ready" | Out-Null

try {
    Invoke-WebRequest -Uri "$BackendUrl/events" -UseBasicParsing -TimeoutSec 10 | Out-Null
    $failures.Add("protected API accepted an unauthenticated request")
    Write-Host "FAIL  protected API authentication" -ForegroundColor Red
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 401) {
        Write-Host "PASS  protected API denies unauthenticated access (401)" -ForegroundColor Green
    } else {
        $failures.Add("protected API denial check: $($_.Exception.Message)")
    }
}

if (-not $env:NETRAKSH_DEMO_USERNAME -or -not $env:NETRAKSH_DEMO_PASSWORD) {
    $failures.Add("set NETRAKSH_DEMO_USERNAME and NETRAKSH_DEMO_PASSWORD for authenticated smoke checks")
} else {
    try {
        $login = Invoke-RestMethod -Method Post -Uri "$BackendUrl/auth/token" -ContentType "application/x-www-form-urlencoded" -Body @{
            username = $env:NETRAKSH_DEMO_USERNAME
            password = $env:NETRAKSH_DEMO_PASSWORD
        } -TimeoutSec 10
        $headers = @{ Authorization = "Bearer $($login.access_token)" }
        Write-Host "PASS  login ($($login.role))" -ForegroundColor Green
        Test-Http "protected events" "$BackendUrl/events?limit=1" $headers | Out-Null
        Test-Http "latest alerts" "$BackendUrl/alerts?limit=1" $headers | Out-Null
        Test-Http "edge/node health" "$BackendUrl/api/nodes/health" $headers | Out-Null

        $ws = [System.Net.WebSockets.ClientWebSocket]::new()
        $ws.Options.AddSubProtocol("netraksh.jwt")
        $ws.Options.AddSubProtocol($login.access_token)
        $wsUri = [Uri]($BackendUrl.Replace("http://", "ws://").Replace("https://", "wss://") + "/ws/dashboard")
        $cts = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(10))
        $ws.ConnectAsync($wsUri, $cts.Token).GetAwaiter().GetResult() | Out-Null
        if ($ws.State -ne [System.Net.WebSockets.WebSocketState]::Open) { throw "WebSocket state is $($ws.State)" }
        Write-Host "PASS  authenticated WebSocket" -ForegroundColor Green
        $ws.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, "smoke complete", [Threading.CancellationToken]::None).GetAwaiter().GetResult() | Out-Null
        $ws.Dispose()
    } catch {
        $failures.Add("authenticated smoke: $($_.Exception.Message)")
        Write-Host "FAIL  authenticated smoke" -ForegroundColor Red
    }
}

if ($failures.Count -gt 0) {
    Write-Host "`nNETRAKSH demo smoke FAILED:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host " - $_" }
    exit 1
}

Write-Host "`nNETRAKSH demo smoke PASSED" -ForegroundColor Green
exit 0
