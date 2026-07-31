param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$BuildEnv = Join-Path $ProjectDir ".venv-build-windows"
$BuildPython = Join-Path $BuildEnv "Scripts\python.exe"
$ExecutablePath = Join-Path $ProjectDir "dist\CSV Cleaner.exe"
$ArchivePath = Join-Path $ProjectDir "dist\CSV-Cleaner-Windows-x64.zip"

if (-not (Get-Command $PythonCommand -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.11 or newer and try again."
}

& $PythonCommand -c "import sys, tkinter; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.11 or newer with Tkinter is required."
}

Set-Location $ProjectDir

Write-Host "Creating the Windows build environment..."
if (Test-Path $BuildEnv) {
    Remove-Item -Recurse -Force $BuildEnv
}
& $PythonCommand -m venv $BuildEnv
if ($LASTEXITCODE -ne 0) {
    throw "The build environment could not be created."
}

Write-Host "Installing dependencies..."
& $BuildPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Pip could not be updated."
}
& $BuildPython -m pip install . pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw "Application dependencies could not be installed."
}

Write-Host "Running tests..."
& $BuildPython -m unittest discover -v
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed. The executable was not built."
}

Write-Host "Building the Windows executable..."
& $BuildPython -m PyInstaller --clean --noconfirm csv_cleaner_windows.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller could not build the executable."
}

if (-not (Test-Path $ExecutablePath)) {
    throw "The build did not create the expected CSV Cleaner.exe file."
}

Write-Host "Creating the release archive..."
if (Test-Path $ArchivePath) {
    Remove-Item -Force $ArchivePath
}
Compress-Archive -LiteralPath $ExecutablePath -DestinationPath $ArchivePath -Force

Write-Host "Done."
Write-Host "Executable: $ExecutablePath"
Write-Host "Release archive: $ArchivePath"
