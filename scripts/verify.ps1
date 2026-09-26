param(
    [switch]$AuditDependencies,
    [switch]$PrePush,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not $Python) {
    $Python = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path $Python)) {
        $Python = Join-Path $root ".venv/bin/python"
    }
    if (-not (Test-Path $Python)) {
        Write-Error "Create .venv and install the project's dev dependencies first, or pass -Python."
        exit 2
    }
}

$arguments = @("scripts/verify.py")
if ($AuditDependencies) { $arguments += "--audit-dependencies" }
if ($PrePush) { $arguments += "--pre-push" }
& $Python @arguments
exit $LASTEXITCODE
