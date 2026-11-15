# Opens the WizExpert workflow console: reuses a ready console for this workspace, otherwise opens
# a standard VS Code window on the outer workspace so its folderOpen task starts the console.
# This script never starts, stops or restarts the backend itself. Workspace = parent of the repo.
param(
    [string]$Workspace = "",
    [int]$Port = 8765,
    [int]$TimeoutSeconds = 90,
    [switch]$NoDialog
)

function Test-ConsoleCommandLine {
    # True only for a console process whose --workspace is exactly this workspace.
    param([string]$CommandLine, [string]$Workspace)
    if (-not $CommandLine -or $CommandLine -inotmatch "\s-m\s+wizexpert(\.console\.dev|\s+console)(\s|$)") { return $false }
    $ws = [regex]::Escape($Workspace.TrimEnd("\"))
    return [bool]($CommandLine -imatch "--workspace\s+`"?$ws\\?`"?(\s|$)")
}

function Get-ConsoleListenerPid {
    param([int]$Port)
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess }
    return 0
}

function Get-ProcessCommandLine {
    param([int]$ProcessId)
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($p) { return [string]$p.CommandLine }
    return ""
}

function Test-ConsoleHttp {
    param([int]$Port)
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Find-CodeExe {
    $cmd = Get-Command code.cmd -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) {
        $exe = Join-Path (Split-Path (Split-Path $cmd.Source -Parent) -Parent) "Code.exe"
        if (Test-Path -LiteralPath $exe) { return $exe }
    }
    foreach ($base in @($env:LOCALAPPDATA, $env:ProgramFiles)) {
        if (-not $base) { continue }
        $exe = Join-Path $base "Programs\Microsoft VS Code\Code.exe"
        if (-not (Test-Path -LiteralPath $exe)) { $exe = Join-Path $base "Microsoft VS Code\Code.exe" }
        if (Test-Path -LiteralPath $exe) { return $exe }
    }
    return $null
}

function Show-ConsoleError {
    param([string]$Message)
    [Console]::Error.WriteLine($Message)
    if (-not $NoDialog) {
        try {
            Add-Type -AssemblyName System.Windows.Forms
            [void][System.Windows.Forms.MessageBox]::Show($Message, "WizExpert console")
        } catch {
            [Console]::Error.WriteLine("Could not show the error dialog: $($_.Exception.Message)")
        }
    }
}

function Get-ConsoleState {
    # ready | starting | occupied | stopped
    param([string]$Workspace, [int]$Port)
    $listener = Get-ConsoleListenerPid -Port $Port
    if ($listener) {
        if (-not (Test-ConsoleCommandLine (Get-ProcessCommandLine $listener) $Workspace)) {
            # A dev watcher may be the parent of the listening child; accept only a matching parent.
            $parent = (Get-CimInstance Win32_Process -Filter "ProcessId=$listener" -ErrorAction SilentlyContinue).ParentProcessId
            if (-not ($parent -and (Test-ConsoleCommandLine (Get-ProcessCommandLine $parent) $Workspace))) {
                return "occupied"
            }
        }
        if (Test-ConsoleHttp -Port $Port) { return "ready" }
        return "starting"
    }
    $match = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { Test-ConsoleCommandLine $_.CommandLine $Workspace } | Select-Object -First 1
    if ($match) { return "starting" }
    return "stopped"
}

function Open-WizExpertConsole {
    param([string]$Workspace, [int]$Port, [int]$TimeoutSeconds)
    $state = Get-ConsoleState $Workspace $Port
    if ($state -eq "occupied") {
        Show-ConsoleError "Port $Port is used by a process that is not the WizExpert console for $Workspace. Nothing was changed; stop that service or free the port, then retry."
        return 2
    }
    if ($state -eq "ready") { Start-Process "http://127.0.0.1:$Port/"; return 0 }
    if ($state -eq "stopped") {
        $code = Find-CodeExe
        if (-not $code) {
            Show-ConsoleError "VS Code (Code.exe next to code.cmd) was not found. Install VS Code or add its bin folder to PATH."
            return 3
        }
        # Standard window; the folderOpen task in the workspace starts the console and opens the browser.
        Start-Process -FilePath $code -ArgumentList @("--new-window", "`"$Workspace`"")
    }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $s = Get-ConsoleState $Workspace $Port
        if ($s -eq "ready") { return 0 }
        if ($s -eq "occupied") {
            Show-ConsoleError "Port $Port was taken by an unrelated process while waiting. Nothing was changed."
            return 2
        }
    }
    Show-ConsoleError ("The console did not become ready within $TimeoutSeconds s. In the VS Code window that opened, " +
        "check that the 'WizExpert: Workflow console (auto-reload)' task is running (allow automatic tasks / trust the folder, " +
        "or run it via Tasks: Run Task). It must be a standard window, not the Agents window.")
    return 1
}

if ($MyInvocation.InvocationName -ne ".") {
    if (-not $Workspace) { $Workspace = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path }
    exit (Open-WizExpertConsole -Workspace $Workspace -Port $Port -TimeoutSeconds $TimeoutSeconds)
}
