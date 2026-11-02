$listeners = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
    $ownerPid = [int]$listener.OwningProcess
    Stop-Process -Id $ownerPid -Force -ErrorAction Stop
    Write-Output "Stopped workflow console process $ownerPid."
}
if (-not $listeners) {
    Write-Output "No workflow console listener found on port 8765."
}
