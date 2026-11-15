# Creates WizExpert.lnk on the current Desktop. An identical shortcut is a no-op; a different
# existing one is reported and never overwritten.
param([string]$Desktop = "")

function Get-ShortcutSpec {
    param([string]$ScriptDir)
    $launcher = (Resolve-Path (Join-Path $ScriptDir "open-console.ps1")).Path
    $workspace = (Resolve-Path (Join-Path $ScriptDir "..\..\..")).Path
    [pscustomobject]@{
        Target  = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        Args    = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
        WorkDir = $workspace
    }
}

function Install-WizExpertShortcut {
    param([string]$Desktop, [string]$ScriptDir)
    $spec = Get-ShortcutSpec $ScriptDir
    $path = Join-Path $Desktop "WizExpert.lnk"
    $shell = New-Object -ComObject WScript.Shell
    if (Test-Path -LiteralPath $path) {
        $e = $shell.CreateShortcut($path)
        if ($e.TargetPath -ieq $spec.Target -and $e.Arguments -ieq $spec.Args -and $e.WorkingDirectory -ieq $spec.WorkDir) {
            Write-Host "Shortcut already up to date: $path"
            return 0
        }
        Write-Error "A different shortcut already exists and was not changed: $path (target: $($e.TargetPath) $($e.Arguments)). Rename or remove it, then rerun."
        return 1
    }
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = $spec.Target
    $s.Arguments = $spec.Args
    $s.WorkingDirectory = $spec.WorkDir
    $s.Description = "Open the WizExpert workflow console"
    $s.WindowStyle = 7
    $s.Save()
    Write-Host "Created shortcut: $path"
    return 0
}

if ($MyInvocation.InvocationName -ne ".") {
    if (-not $Desktop) { $Desktop = [Environment]::GetFolderPath("DesktopDirectory") }
    exit (Install-WizExpertShortcut -Desktop $Desktop -ScriptDir $PSScriptRoot)
}
