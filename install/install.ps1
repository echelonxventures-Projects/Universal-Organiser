# Universal Organiser installer for Windows 10/11.
#   powershell -ExecutionPolicy Bypass -File install\install.ps1 [-Dir FOLDER] [-Yes] [-NoStart] [-Autostart]
# Run it again later to update: program files are replaced, your profile, catalogue and logs are kept.
param([string]$Dir = "$env:LOCALAPPDATA\Universal Organiser", [switch]$Yes, [switch]$NoStart, [switch]$Autostart)
$ErrorActionPreference = "Stop"
$Src = Split-Path -Parent $PSScriptRoot

function Ask($q) { if ($Yes) { return $true }; $a = Read-Host "$q [y/N]"; return $a -match '^(y|yes)$' }

$os = (Get-CimInstance Win32_OperatingSystem)
Write-Host "Universal Organiser - installing for Windows ($($os.Caption), $env:PROCESSOR_ARCHITECTURE)"
Write-Host "  program and your data: $Dir"

# ---- Python 3.9+
function Find-Python {
  foreach ($c in @(@("py", "-3"), @("python"))) {
    $exe = Get-Command $c[0] -ErrorAction SilentlyContinue
    if ($exe) {
      $args = @(); if ($c.Length -gt 1) { $args += $c[1] }
      & $c[0] @args -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
      if ($LASTEXITCODE -eq 0) { return ,$c }
    }
  }
  return $null
}
$py = Find-Python
if (-not $py) {
  Write-Host "Python 3.9 or newer is needed and was not found."
  if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Ask "Install Python 3.12 now with winget?")) {
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    $py = Find-Python
  }
  if (-not $py) { Write-Host "Install Python from https://www.python.org/downloads/ (tick 'Add to PATH'), then run this installer again."; exit 1 }
}
$pyArgs = @(); if ($py.Length -gt 1) { $pyArgs += $py[1] }
Write-Host "  Python: $(& $py[0] @pyArgs -c 'import sys; print(sys.version.split()[0])')"

# ---- disk encryption (the catalogue holds your documents' text)
try {
  $bl = (New-Object -ComObject Shell.Application).NameSpace("$($env:SystemDrive)\").Self.ExtendedProperty("System.Volume.BitLockerProtection")
} catch { $bl = $null }
if ($bl -ne 1 -and $bl -ne 3) {
  Write-Host ""
  Write-Host "Disk encryption is OFF on $env:SystemDrive. Universal Organiser will not store a catalogue on an unencrypted disk."
  Write-Host "  Turn it on: Settings > Privacy & security > Device encryption (or BitLocker), then run this installer again."
  if (Ask "Open that Settings page now?") { Start-Process "ms-settings:deviceencryption" }
}

# ---- copy the program (never the data)
New-Item -ItemType Directory -Force -Path $Dir, "$Dir\profiles", "$Dir\helpers\macos" | Out-Null
if ((Resolve-Path $Src).Path -ne (Resolve-Path $Dir).Path) {
  if (Test-Path "$Dir\engine") { Write-Host "  existing install found: updating the program files only"; Remove-Item -Recurse -Force "$Dir\engine" }
  Copy-Item -Recurse "$Src\engine" "$Dir\engine"
  foreach ($d in "presets", "regions") { if (Test-Path "$Dir\profiles\$d") { Remove-Item -Recurse -Force "$Dir\profiles\$d" }; Copy-Item -Recurse "$Src\profiles\$d" "$Dir\profiles\$d" }
  Copy-Item "$Src\profiles\base.json" "$Dir\profiles\base.json" -Force
  foreach ($d in "docs", "install") { if (Test-Path "$Dir\$d") { Remove-Item -Recurse -Force "$Dir\$d" }; Copy-Item -Recurse "$Src\$d" "$Dir\$d" }
  foreach ($f in "uo", "uo.cmd", "fe", "fe.cmd", "README.md", "LICENSE", "CHANGELOG.md", "SECURITY.md") { if (Test-Path "$Src\$f") { Copy-Item "$Src\$f" "$Dir\$f" -Force } }
  Get-ChildItem -Recurse -Directory -Filter __pycache__ "$Dir\engine" | Remove-Item -Recurse -Force
}

# ---- Start menu shortcut + 'uo' on the user PATH
$sm = Join-Path ([Environment]::GetFolderPath("Programs")) "Universal Organiser.lnk"
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($sm); $lnk.TargetPath = "$Dir\uo.cmd"; $lnk.Arguments = "serve"; $lnk.WorkingDirectory = $Dir
$lnk.Description = "Universal Organiser: find and organise your files"; $lnk.Save()
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not ($userPath -split ";" | Where-Object { $_ -eq $Dir })) {
  [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $Dir), "User")
  Write-Host "  added $Dir to your PATH (new terminals can type 'uo')"
}

# ---- PDF text
if (-not (Get-Command pdftotext -ErrorAction SilentlyContinue)) {
  Write-Host "  Optional: for text inside PDFs install Poppler (see docs\manual.md, 'PDF text on Windows')."
}

Write-Host ""
& "$Dir\uo.cmd" doctor
if ($Autostart) { & "$Dir\uo.cmd" autostart on }
Write-Host ""
if (-not $NoStart) {
  Write-Host "Starting. Your browser opens the page: create the admin account, then the set-up wizard asks the rest."
  & "$Dir\uo.cmd" serve
} else { Write-Host "Done. Start it from the Start menu (Universal Organiser) or with:  uo serve" }
