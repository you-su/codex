$ErrorActionPreference = 'Stop'
$base = 'http://127.0.0.1:8765'
try {
    $page = Invoke-WebRequest -Uri $base -UseBasicParsing -TimeoutSec 60
} catch {
    Write-Host 'Cannot reach the terminal. It may already be stopped. If it is busy, wait and retry.'
    exit 1
}
if ($page.Content -notmatch '<title>大肥鱼 API 模型终端</title>') {
    Write-Host 'Port 8765 is not a recognized BigFish terminal. No process was stopped.'
    exit 1
}
$tokenMatch = [regex]::Match($page.Content, "'X-Local-Token':'([^']+)'")
if (-not $tokenMatch.Success) {
    Write-Host 'Cannot verify the local session. Close the original terminal window manually.'
    exit 1
}
try {
    $result = Invoke-RestMethod -Uri "$base/api/shutdown" -Method Post -Headers @{'X-Local-Token'=$tokenMatch.Groups[1].Value} -ContentType 'application/json' -Body '{}' -TimeoutSec 60
    if ($result.ok -eq $true) {
        Write-Host 'Shutdown requested successfully. You can now close the old terminal window.'
        exit 0
    }
} catch {
    if (-not $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 400) {
        Write-Host 'Shutdown was not confirmed. Wait for any active operation and retry.'
        exit 1
    }
}
# Older releases have no shutdown endpoint. Match both the recognized web app
# and the Python server process listening on its local port before stopping it.
try {
    $listeners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen | Where-Object { $_.LocalAddress -eq '127.0.0.1' })
    $processIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($processIds.Count -ne 1) { throw 'Ambiguous listener; refusing to stop.' }
    $targetId = $processIds[0]
    $target = Get-CimInstance Win32_Process -Filter "ProcessId=$targetId"
    if ($target.Name -notmatch '^python(?:w|[0-9.]*)?\.exe$' -or $target.CommandLine -notmatch '(?i)(?:^|[\s"\\/])server\.py(?:["\s]|$)') {
        throw 'The listener is not a recognized Python server.py process.'
    }
    # Re-check the process identity immediately before termination.
    $current = Get-CimInstance Win32_Process -Filter "ProcessId=$targetId"
    if ($current.CreationDate -ne $target.CreationDate -or $current.CommandLine -ne $target.CommandLine) { throw 'Process identity changed.' }
    Stop-Process -Id $targetId -ErrorAction Stop
    Write-Host 'Old BigFish terminal stopped. Its console window can now be closed.'
} catch {
    Write-Host ('Unable to safely stop the old version: ' + $_.Exception.Message)
    Write-Host 'Close its original terminal window manually. Other Python programs were not stopped.'
    exit 1
}

