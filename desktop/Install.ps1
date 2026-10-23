# Install the Process Engineering Toolbox as a desktop app (Windows, per-user).
#
#   powershell -ExecutionPolicy Bypass -File desktop\Install.ps1             # install
#   powershell -ExecutionPolicy Bypass -File desktop\Install.ps1 -Uninstall  # remove shortcuts
#
# Creates the .venv and installs dependencies if missing, then adds
# "Process Engineering Toolbox" shortcuts to the Desktop and Start menu.
# Nothing is copied: the shortcuts run the repo in place, so `git pull` updates the app.
# No admin rights needed.

param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Name = 'Process Engineering Toolbox'
$Links = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$Name.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Programs')) "$Name.lnk")
)

if ($Uninstall) {
    foreach ($l in $Links) { if (Test-Path $l) { Remove-Item $l; Write-Host "Removed $l" } }
    Write-Host 'Shortcuts removed. The repo, .venv and %LOCALAPPDATA%\ProcessToolbox are untouched.'
    return
}

$Py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) {
    Write-Host 'Creating Python environment (.venv)...'
    & python -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'python -m venv failed. Is Python 3.11+ on PATH?' }
    Write-Host 'Installing dependencies (a few minutes the first time)...'
    & $Py -m pip install -e "$Root[dev]"
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }
    # Same stamp the launcher checks, so the first launch skips a redundant sync.
    $hash = (Get-FileHash (Join-Path $Root 'pyproject.toml') -Algorithm SHA256).Hash.ToLower()
    Set-Content -Path (Join-Path $Root '.venv\toolbox-deps.sha256') -Value $hash -NoNewline -Encoding ascii
}

$Shell = New-Object -ComObject WScript.Shell
foreach ($l in $Links) {
    $s = $Shell.CreateShortcut($l)
    $s.TargetPath = Join-Path $Root '.venv\Scripts\pythonw.exe'
    $s.Arguments = '"' + (Join-Path $PSScriptRoot 'launch_toolbox.pyw') + '"'
    $s.WorkingDirectory = $Root
    $s.IconLocation = (Join-Path $PSScriptRoot 'toolbox.ico') + ',0'
    $s.Description = 'Launch the Process Engineering Toolbox'
    $s.Save()
    Write-Host "Created $l"
}
Write-Host "`nDone. Launch '$Name' from the Desktop or Start menu (right-click > Pin to taskbar if you like)."
