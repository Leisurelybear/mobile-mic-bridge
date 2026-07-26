$ErrorActionPreference = 'Stop'

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw 'Flutter is not installed or is not available in PATH.'
}

$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    flutter create --platforms=android,ios --project-name mobile_mic_bridge .
    Copy-Item tool\AndroidManifest.xml android\app\src\main\AndroidManifest.xml -Force
    $androidPackage = 'android\app\src\main\kotlin\com\example\mobile_mic_bridge'
    New-Item -ItemType Directory -Path $androidPackage -Force | Out-Null
    Copy-Item tool\android\*.kt $androidPackage -Force
    Copy-Item tool\Info.plist ios\Runner\Info.plist -Force
    Copy-Item tool\ios\AppDelegate.swift ios\Runner\AppDelegate.swift -Force
    flutter pub get
}
finally {
    Pop-Location
}
