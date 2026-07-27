# Start Mobile Mic Bridge Windows receiver (GUI by default).
#
# Usage:
#   .\start-receiver.ps1
#   .\start-receiver.bat
#   .\start-receiver.ps1 -Cli
#   .\start-receiver.ps1 -Cli -ListDevices
#   .\start-receiver.ps1 -Cli -Token secret -Device 12
#   .\start-receiver.ps1 -Rebuild

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

if (-not (Test-Path $ReceiverDir)) {
    Write-Error "windows_receiver not found under $RepoRoot"
}

function Test-PythonLauncher {
    param([string]$Command, [string[]]$PrefixArgs = @())
    try {
        $out = & $Command @PrefixArgs -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True')
    } catch {
        return $false
    }
}

function Test-PackageImportable {
    if (-not (Test-Path $VenvPython)) {
        return $false
    }
    & $VenvPython -c "import mobile_mic_receiver, mobile_mic_receiver.gui.app" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Install-Package {
    Write-Host 'Installing mobile-mic-receiver into venv...'
    # Clear partial/broken pip installs left by interrupted upgrades.
    Get-ChildItem (Join-Path $VenvDir 'Lib\site-packages') -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like '~*' -or $_.Name -like '*mobile_mic_receiver*' -or $_.Name -like '*mobile-mic-receiver*' } |
        ForEach-Object {
            try { Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue } catch {}
        }
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'pip upgrade failed.'
    }
    & $VenvPython -m pip install -e $ReceiverDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'pip install failed.'
    }
    if (-not (Test-PackageImportable)) {
        Write-Error 'Package installed but still not importable. Try: .\start-receiver.ps1 -Rebuild'
    }
}

function Ensure-Venv {
    if ($Rebuild -and (Test-Path $VenvDir)) {
        Write-Host "Removing old venv at $VenvDir ..."
        Remove-Item -Recurse -Force $VenvDir
    }
    if (Test-Path $VenvPython) {
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
}

function Ensure-Package {
    if ((-not $Rebuild) -and (Test-PackageImportable)) {
        return
    }
    Install-Package
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
    Ensure-Package

    if ($Cli) {
        $cliArgs = @(Build-CliArgs)
        Write-Host 'Starting console receiver...'
        if ($cliArgs.Count -gt 0) {
            & $VenvPython -m mobile_mic_receiver.cli @cliArgs
        } else {
            & $VenvPython -m mobile_mic_receiver.cli
        }
    } else {
        if ($ListDevices -or $Token -or $Device -or $Port -gt 0 -or $HostAddress -or $QrMode -or $NoDiscovery -or $NoQr) {
            Write-Warning 'CLI options ignored in GUI mode. Use -Cli, or configure options in the window.'
        }
        Write-Host 'Starting GUI receiver (HTTPS web QR pairing enabled)...'
        # Launch via package __main__ so a broken console script / partial pip
        # install cannot hide the package, and avoid runpy double-import warnings.
        & $VenvPython -m mobile_mic_receiver.gui
    }
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
