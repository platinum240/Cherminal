# Build Cherminal for 64-bit Windows: the app folder (Cherminal.exe and
# cherminal-cli.exe with their own Python and Qt), then
#   dist\Cherminal-<version>-windows-x64.msi   installer for all users; what
#                                              Intune, ConfigMgr and GPO deploy
#   dist\Cherminal-<version>-windows-x64.zip   portable: unzip and run
#
# Run from PowerShell 7 on Windows with Python 3.11 or later and the .NET SDK
# (for the WiX Toolset, installed here if it is missing). Needs network
# access at build time (PyPI, NuGet); the app needs nothing.
#
# Unsigned: signing happens separately (docs/WINDOWS.md).
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
Set-Location (Join-Path $PSScriptRoot "..")
if (-not $IsWindows) { throw "build-windows.ps1 runs on Windows" }

$version = (Select-String -Path cherminal\__init__.py -Pattern '^__version__ = "(.*)"').Matches[0].Groups[1].Value
$build = "build\windows"
$name = "Cherminal-$version-windows-x64"
Remove-Item -Recurse -Force "$build\work", "$build\dist" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $build, dist | Out-Null

# A clean environment with only Cherminal's dependencies and PyInstaller.
python -m venv "$build\venv"
$python = "$build\venv\Scripts\python.exe"
& $python -m pip install -q --upgrade pip
& $python -m pip install -q . pyinstaller

& $python -m PyInstaller --noconfirm --clean --log-level WARN `
    --distpath "$build\dist" --workpath "$build\work" packaging\windows\cherminal.spec
$app = Resolve-Path "$build\dist\Cherminal"

# Smoke test: the bundled interpreter starts and finds its modules.
$cli = Join-Path $app "cherminal-cli.exe"
& $cli --version
$env:XDG_CONFIG_HOME = Join-Path $build "smoke-config"
& $cli --list
Remove-Item Env:XDG_CONFIG_HOME
& $cli keycapture --help

# Portable zip: the Cherminal folder as it is.
Remove-Item -Force "dist\$name.zip" -ErrorAction SilentlyContinue
Compress-Archive -Path $app -DestinationPath "dist\$name.zip"

# Installer, with the WiX Toolset (a .NET tool).
$env:PATH += ";$env:USERPROFILE\.dotnet\tools"
if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
    dotnet tool install --global wix --version 5.0.2
}
wix build packaging\windows\cherminal.wxs -arch x64 `
    -d "Version=$version" -d "AppDir=$app" `
    -d "IconFile=$(Resolve-Path packaging\windows\cherminal.ico)" `
    -o "dist\$name.msi"
Remove-Item -Force "dist\$name.wixpdb" -ErrorAction SilentlyContinue
Write-Host "Built dist\$name.msi and dist\$name.zip"
