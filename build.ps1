# Dofus Manager — compilation (et signature optionnelle) de l'exécutable Windows.
#   .\build.ps1                                        -> dist\DofusManager-<version>-windows.exe
#   .\build.ps1 -CertPath cert.pfx -CertPassword xxx   -> exe signé (certificat de signature de code)
#   .\build.ps1 -Python python                         -> autre interpréteur que « py -3.13 » (CI)
# La version vient de APP_VERSION (dm_core.py), via tools\version.py : jamais saisie ici.
param([string]$CertPath = "", [string]$CertPassword = "", [string]$Python = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-Checked { & $args[0] $args[1..($args.Length - 1)]; if ($LASTEXITCODE -ne 0) { throw "Échec : $args" } }

if (-not (Test-Path .venv-win\Scripts\python.exe)) {
    if ($Python) { Invoke-Checked $Python -m venv .venv-win } else { Invoke-Checked py -3.13 -m venv .venv-win }
}
$py = (Resolve-Path .venv-win\Scripts\python.exe).Path
Invoke-Checked $py -m pip install -q --upgrade pip
Invoke-Checked $py -m pip install -q -r requirements-win.txt

$version = (& $py tools\version.py).Trim()
if ($LASTEXITCODE -ne 0) { throw "Version illisible" }
New-Item -ItemType Directory -Force build | Out-Null
Invoke-Checked $py tools\version.py --win-file build\version_info.txt
Invoke-Checked $py -c "from dm_widgets import make_app_icon; make_app_icon(256).save('build/icon.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

Invoke-Checked $py -m PyInstaller --noconfirm --onefile --windowed --name DofusManager `
    --icon build\icon.ico --version-file build\version_info.txt `
    --add-data "assets/classes;assets/classes" `
    --collect-data customtkinter --hidden-import pystray._win32 --hidden-import PIL._tkinter_finder `
    --exclude-module dm_mac `
    dofus_manager.py

if ($CertPath) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe `
                -ErrorAction SilentlyContinue | Where-Object FullName -like "*\x64\*" | Select-Object -Last 1
    if (-not $signtool) { throw "signtool.exe introuvable : installez le Windows SDK (composant « Signing Tools »)." }
    & $signtool.FullName sign /f $CertPath /p $CertPassword /fd SHA256 `
        /tr http://timestamp.digicert.com /td SHA256 /d "Dofus Manager" dist\DofusManager.exe
    if ($LASTEXITCODE -ne 0) { throw "Échec de la signature" }
}

# Contrôle : la version inscrite dans l'exe doit être celle de dm_core.py.
$expected = (& $py tools\version.py --win).Trim()
$actual = (Get-Item dist\DofusManager.exe).VersionInfo.ProductVersion
if ($actual -ne $expected) { throw "Version de l'exe ($actual) différente de APP_VERSION ($expected)" }

$out = "dist\DofusManager-$version-windows.exe"
Move-Item -Force dist\DofusManager.exe $out
Remove-Item -Recurse -Force build, DofusManager.spec -ErrorAction SilentlyContinue
Write-Host "OK : $out (version $actual)"
