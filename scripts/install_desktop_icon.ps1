$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Venv       = Join-Path $RepoRoot ".venv"
$PythonExe  = Join-Path $Venv "Scripts\python.exe"
$PythonwExe = Join-Path $Venv "Scripts\pythonw.exe"

Write-Host "TopShelf installer..."

if (-not (Test-Path $PythonExe)) {
    Write-Host "Creating venv..."
    python -m venv $Venv
}

Write-Host "Installing deps..."
& $PythonExe -m pip install --upgrade pip --quiet
& $PythonExe -m pip install -r (Join-Path $RepoRoot "requirements.txt") --quiet

Write-Host "Generating icon..."
& $PythonExe (Join-Path $RepoRoot "scripts\make_icon.py")

$IconPath = Join-Path $RepoRoot "assets\topshelf.ico"
if (-not (Test-Path $IconPath)) {
    throw "Icon was not generated"
}

$Launcher = if (Test-Path $PythonwExe) { $PythonwExe } else { $PythonExe }

$Desktop  = [Environment]::GetFolderPath("Desktop")
$LnkPath  = Join-Path $Desktop "TopShelf.lnk"

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($LnkPath)
$Shortcut.TargetPath       = $Launcher
$Shortcut.Arguments        = "tray_app.py"
$Shortcut.WorkingDirectory = $RepoRoot
$Shortcut.IconLocation     = $IconPath
$Shortcut.Description       = "TopShelf launcher"
$Shortcut.WindowStyle      = 7
$Shortcut.Save()

Write-Host "Done - Shortcut created on Desktop"
