# Runs the workflow console for this workspace and stops it when the owning VS Code exits.
param([int]$OwnerPid = 0)
$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repo = Join-Path $workspace "WizExpert"
$python = Join-Path $repo ".venv\Scripts\python.exe"

# Owning VS Code = nearest Code.exe ancestor of this script.
$owner = if ($OwnerPid) { $OwnerPid } else { $null }
$id = if ($OwnerPid) { 0 } else { $PID }
for ($i = 0; $i -lt 10 -and $id; $i++) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id"
    if (-not $p) { break }
    if ($p.Name -eq "Code.exe" -and $p.ProcessId -ne $PID) { $owner = $p.ProcessId }
    $id = $p.ParentProcessId
}

if (-not $owner) {
    Write-Warning "No owning Code.exe ancestor found; the console will NOT auto-stop when VS Code exits. Run stop-console.ps1 to stop it."
}

$console = Start-Process -FilePath $python -NoNewWindow -PassThru -WorkingDirectory $repo -ArgumentList @(
    "-m", "wizexpert.console.dev",
    "--watch-root", "`"$repo\wizexpert\console`"",
    "--workspace", "`"$workspace`"",
    "--port", "8765"
)
Write-Output "Workflow console PID $($console.Id); stops when VS Code PID $owner exits."

while (-not $console.HasExited) {
    if ($owner -and -not (Get-Process -Id $owner -ErrorAction SilentlyContinue)) {
        & taskkill.exe /PID $console.Id /T /F | Out-Null
        break
    }
    Start-Sleep -Seconds 3
}
