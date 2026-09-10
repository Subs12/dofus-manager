# Dofus Manager — compilation (et signature optionnelle) de l'exécutable.
#   .\build.ps1                                        -> exe non signé
#   .\build.ps1 -CertPath cert.pfx -CertPassword xxx   -> exe signé (certificat de signature de code)
param([string]$CertPath = "", [string]$CertPassword = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

py -3.13 -c "from dm_widgets import make_app_icon; make_app_icon(256).save('assets/icon.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

py -3.13 -m PyInstaller --noconfirm --onefile --windowed --name DofusManager `
    --icon assets/icon.ico --version-file assets/version_info.txt `
    --add-data "assets/classes;assets/classes" `
    --collect-data customtkinter --hidden-import pystray._win32 --hidden-import PIL._tkinter_finder `
    dofus_manager.py
if ($LASTEXITCODE -ne 0) { throw "Échec de PyInstaller" }

if ($CertPath) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe `
                -ErrorAction SilentlyContinue | Where-Object FullName -like "*\x64\*" | Select-Object -Last 1
    if (-not $signtool) { throw "signtool.exe introuvable : installez le Windows SDK (composant « Signing Tools »)." }
    & $signtool.FullName sign /f $CertPath /p $CertPassword /fd SHA256 `
        /tr http://timestamp.digicert.com /td SHA256 /d "Dofus Manager" dist\DofusManager.exe
    if ($LASTEXITCODE -ne 0) { throw "Échec de la signature" }
}

Remove-Item -Recurse -Force build, DofusManager.spec -ErrorAction SilentlyContinue
Write-Host "OK : dist\DofusManager.exe"
