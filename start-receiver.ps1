# Start Mobile Mic Bridge Windows receiver (GUI by default).
#
# Usage:
#   .\start-receiver.ps1
#   .\start-receiver.bat
#   .\start-receiver.ps1 -Cli
#   .\start-receiver.ps1 -Cli -ListDevices
#   .\start-receiver.ps1 -Cli -Token secret -Device 12
#   .\start-receiver.ps1 -Rebuild
#
# After the first run, you can also call entry points directly:
#   .\windows_receiver\.venv\Scripts\mobile-mic-receiver-gui.exe
#   .\windows_receiver\.venv\Scripts\mobile-mic-receiver.exe --help

[CmdletBinding()]
param(
    [switch]$Cli,
    [switch]$Rebuild,
    [switch]$ListDevices,
    [string]$Token = '',
    [string]$Device = '',
    [int]$Port = 0,
    [string]$HostAddress = '',
    [ValidateSet('web', 'app', 'both')]
    [string]$QrMode = '',
    [switch]$NoDiscovery,
    [switch]$NoQr
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReceiverDir = Join-Path $RepoRoot 'windows_receiver'
$VenvDir = Join-Path $ReceiverDir '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$VenvGui = Join-Path $VenvDir 'Scripts\mobile-mic-receiver-gui.exe'
$VenvCli = Join-Path $VenvDir 'Scripts\mobile-mic-receiver.exe'

if (-not (Test-Path $ReceiverDir)) {
    Write-Error "windows_receiver not found under $RepoRoot"
}

function Test-PythonLauncher {
    param([string]$Command, [string[]]$PrefixArgs = @())
    try {
        $out = & $Command @PrefixArgs -c "import sys; print(sys.version_info -ge (3, 10))" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True')
    } catch {
        return $false
    }
}

function Ensure-Venv {
    if ((Test-Path $VenvPython) -and -not $Rebuild) {
        return
    }

    $createArgs = $null
    if (Test-PythonLauncher -Command 'py' -PrefixArgs @('-3.11')) {
        $createArgs = @('py', '-3.11', '-m', 'venv', $VenvDir)
    } elseif (Test-PythonLauncher -Command 'py' -PrefixArgs @('-3')) {
        $createArgs = @('py', '-3', '-m', 'venv', $VenvDir)
    } elseif (Test-PythonLauncher -Command 'python') {
        $createArgs = @('python', '-m', 'venv', $VenvDir)
    } else {
        Write-Error 'Python 3.10+ not found. Install Python and ensure py/python is on PATH.'
    }

    Write-Host "Creating venv at $VenvDir ..."
    & $createArgs[0] $createArgs[1..($createArgs.Length - 1)]
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) {
        Write-Error 'Failed to create virtual environment.'
    }
    Write-Host 'Installing mobile-mic-receiver (editable)...'
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'pip upgrade failed.'
    }
    & $VenvPython -m pip install -e $ReceiverDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'pip install failed.'
    }
}

function Ensure-EntryPoints {
    if ((Test-Path $VenvGui) -and (Test-Path $VenvCli) -and -not $Rebuild) {
        return
    }
    Write-Host 'Refreshing package install for entry points...'
    & $VenvPython -m pip install -e $ReceiverDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'pip install failed.'
    }
}

function Build-CliArgs {
    $result = [System.Collections.Generic.List[string]]::new()
    if ($ListDevices) { [void]$result.Add('--list-devices') }
    if ($Token) {
        [void]$result.Add('--token')
        [void]$result.Add($Token)
    }
    if ($Device) {
        [void]$result.Add('--device')
        [void]$result.Add($Device)
    }
    if ($Port -gt 0) {
        [void]$result.Add('--port')
        [void]$result.Add("$Port")
    }
    if ($HostAddress) {
        [void]$result.Add('--host')
        [void]$result.Add($HostAddress)
    }
    if ($QrMode) {
        [void]$result.Add('--qr-mode')
        [void]$result.Add($QrMode)
    }
    if ($NoDiscovery) { [void]$result.Add('--no-discovery') }
    if ($NoQr) { [void]$result.Add('--no-qr') }
    return , $result.ToArray()
}

Push-Location $ReceiverDir
try {
    Ensure-Venv
    Ensure-EntryPoints

    if ($Cli) {
        $cliArgs = @(Build-CliArgs)
        Write-Host 'Starting console receiver...'
        if ($cliArgs.Count -gt 0) {
            & $VenvCli @cliArgs
        } else {
            & $VenvCli
        }
    } else {
        if ($ListDevices -or $Token -or $Device -or $Port -gt 0 -or $HostAddress -or $QrMode -or $NoDiscovery -or $NoQr) {
            Write-Warning 'CLI options ignored in GUI mode. Use -Cli, or configure options in the window.'
        }
        Write-Host 'Starting GUI receiver (web QR pairing enabled)...'
        & $VenvGui
    }
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
