$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$processes = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and
    $_.CommandLine -match ('(?i)' + [regex]::Escape($workspace.TrimEnd('\')) + '\\?("|\s|$)') -and
    ($_.CommandLine.Contains("wizexpert.console.dev") -or $_.CommandLine -match 'wizexpert(\.exe)?"?\s+console')
}

foreach ($process in $processes) {
    & taskkill.exe /PID $process.ProcessId /T /F 2>$null | Out-Null
    Write-Output "Stopped workflow console process $($process.ProcessId)."
}
if (-not $processes) {
    Write-Output "No workflow console for $workspace found."
}
# Report (never kill) a listener on the canonical port that belongs to another workspace.
$listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Output "Port 8765 is still in use (PID $($listener.OwningProcess)); it is not the canonical console for $workspace."
}
