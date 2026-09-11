# -*- coding: utf-8 -*-
"""Dofus Manager — vérification et installation des mises à jour.

Le dépôt GitHub est public : on interroge directement l'API des releases, sans
compte ni outil à installer. Hors ligne, la vérification échoue simplement.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

import dm_core as core

REPO = "Subs12/dofus-manager"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_HEADERS = {"User-Agent": f"DofusManager/{core.APP_VERSION}", "Accept": "application/vnd.github+json"}
_CREATE_NO_WINDOW = 0x08000000
_MIN_EXE_SIZE = 5_000_000  # un exe valide fait ~30 Mo ; en dessous, le téléchargement est incomplet


def _open(url, timeout):
    return urllib.request.urlopen(urllib.request.Request(url, headers=_HEADERS), timeout=timeout)


def _version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def check_update():
    """(tag, notes, asset) si une version plus récente est publiée avec un .exe, sinon None.

    Lève OSError si GitHub est injoignable.
    """
    if not getattr(sys, "frozen", False):
        return None  # rien à vérifier hors exe compilé (mode développement)
    with _open(_API, 15) as r:
        data = json.load(r)
    asset = next((a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")), None)
    tag = data.get("tag_name", "")
    if asset and _version_tuple(tag) > _version_tuple(core.APP_VERSION):
        return tag, (data.get("body") or "").strip(), {"url": asset["browser_download_url"],
                                                       "size": asset.get("size", 0)}
    return None


def download(tag, asset):
    """Télécharge l'exe de la release dans un dossier temporaire. Retourne son chemin."""
    path = pathlib.Path(tempfile.mkdtemp(prefix="dofusmanager_update_")) / "DofusManager.exe"
    try:
        with _open(asset["url"], 30) as r, open(path, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    except OSError as e:
        raise RuntimeError(f"échec du téléchargement de {tag} ({e})") from e
    size = path.stat().st_size
    if size < _MIN_EXE_SIZE or (asset.get("size") and size != asset["size"]):
        raise RuntimeError("fichier téléchargé incomplet ou corrompu")
    return path


def install_and_restart(new_exe_path):
    """Remplace l'exe courant par le nouveau et relance l'application.

    L'exe en cours d'exécution est verrouillé par Windows : impossible de
    l'écraser directement. On délègue le remplacement à un script batch qui
    attend la fin du process courant, copie le nouvel exe, le relance, puis
    s'auto-supprime.

    L'ancien exe est d'abord sauvegardé en ".bak" : si la copie du nouveau
    échoue ou produit un exécutable qui ne démarre pas, l'utilisateur peut
    restaurer manuellement l'ancienne version sans tout réinstaller.
    """
    current = pathlib.Path(sys.executable)
    pid = os.getpid()
    bat = pathlib.Path(tempfile.gettempdir()) / f"dofusmanager_update_{pid}.bat"
    # cmd lit un .bat dans la page de code OEM (850) : un chemin UTF-8 contenant « é »
    # (C:\Users\Grégory\...) y serait illisible. Le script reste donc 100 % ASCII et les
    # chemins passent par des variables d'environnement (bloc d'environnement Unicode).
    # En --onefile, le bootloader parent garde l'exe verrouillé un court instant après la
    # fin de notre PID : la copie est retentée plutôt que supposée immédiate.
    bat.write_text(
        "@echo off\r\n"
        ":wait\r\n"
        'tasklist /FI "PID eq %DM_PID%" 2>nul | find "%DM_PID%" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  ping -n 2 127.0.0.1 >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        'copy /y "%DM_CUR%" "%DM_BAK%" >nul 2>&1\r\n'
        "set /a DM_TRY=0\r\n"
        ":copy\r\n"
        'copy /y "%DM_NEW%" "%DM_CUR%" >nul 2>&1\r\n'
        "if errorlevel 1 (\r\n"
        "  set /a DM_TRY+=1\r\n"
        "  if %DM_TRY% LSS 30 (\r\n"
        "    ping -n 2 127.0.0.1 >nul\r\n"
        "    goto copy\r\n"
        "  )\r\n"
        ")\r\n"
        'start "" "%DM_CUR%"\r\n'
        'del "%DM_NEW%" >nul 2>&1\r\n'
        'del "%~f0"\r\n',
        encoding="ascii",
    )
    env = dict(os.environ, DM_PID=str(pid), DM_CUR=str(current), DM_NEW=str(new_exe_path),
               DM_BAK=str(current) + ".bak",
               # Sans ça, le nouvel exe hériterait de l'environnement du bootloader PyInstaller
               # courant et tenterait de réutiliser son dossier temporaire (supprimé).
               PYINSTALLER_RESET_ENVIRONMENT="1")
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=_CREATE_NO_WINDOW, env=env,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, cwd=tempfile.gettempdir())
    core.log.info("Mise à jour : redémarrage vers %s", new_exe_path)
