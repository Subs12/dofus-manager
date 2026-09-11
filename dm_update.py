# -*- coding: utf-8 -*-
"""Dofus Manager — vérification et installation des mises à jour.

Le dépôt GitHub étant privé, l'API des releases n'est pas accessible publiquement.
On passe donc par GitHub CLI (`gh`), déjà authentifié sur ce PC, plutôt que
d'embarquer un jeton d'accès dans l'exécutable. Sans `gh` installé/connecté,
la vérification est simplement ignorée : jamais d'erreur bloquante pour l'utilisateur.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import dm_core as core

REPO = "Subs12/dofus-manager"
_GH = shutil.which("gh")
_CREATE_NO_WINDOW = 0x08000000


def _run(args, timeout=20, capture_stdout=True):
    if not _GH:
        return None
    out = subprocess.PIPE if capture_stdout else subprocess.DEVNULL
    try:
        # gh sort de l'UTF-8 : sans encoding explicite, les notes accentuées sont décodées en cp1252.
        # stdin/stderr explicites : un exe --windowed n'a pas de handles standard valides.
        r = subprocess.run([_GH, *args], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.PIPE,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=_CREATE_NO_WINDOW)
        if r.returncode != 0:
            core.log.debug("gh %s -> %s : %s", args, r.returncode, (r.stderr or "").strip()[:300])
            return None
        return r.stdout if capture_stdout else ""
    except Exception as e:
        core.log.debug("gh %s: %s", args, e)
        return None


def _version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def available():
    return bool(_GH)


def check_update():
    """(tag, notes, asset_name) si une version plus récente est publiée avec un .exe, sinon None."""
    if not _GH or not getattr(sys, "frozen", False):
        return None  # rien à vérifier hors exe compilé (mode développement)
    out = _run(["release", "view", "--repo", REPO, "--json", "tagName,body,assets"])
    if not out:
        return None
    try:
        data = json.loads(out)
        asset = next((a["name"] for a in data.get("assets", []) if a["name"].endswith(".exe")), None)
        if asset and _version_tuple(data["tagName"]) > _version_tuple(core.APP_VERSION):
            return data["tagName"], (data.get("body") or "").strip(), asset
    except Exception as e:
        core.log.warning("Vérification des mises à jour : %s", e)
    return None


_MIN_EXE_SIZE = 5_000_000  # un exe valide fait ~30 Mo ; en dessous, le téléchargement est incomplet


def download(tag, asset_name, progress=None):
    """Télécharge l'exe de la release dans un dossier temporaire. Retourne son chemin."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dofusmanager_update_"))
    if progress:
        progress("Téléchargement…")
    out = _run(["release", "download", tag, "--repo", REPO, "--pattern", "*.exe",
               "--dir", str(tmp), "--clobber"], timeout=180, capture_stdout=False)
    if out is None:
        raise RuntimeError("Échec du téléchargement (GitHub CLI).")
    found = list(tmp.glob("*.exe"))
    if not found:
        raise RuntimeError("Aucun exécutable trouvé dans la release.")
    path = found[0]
    if path.stat().st_size < _MIN_EXE_SIZE:
        raise RuntimeError("Fichier téléchargé incomplet ou corrompu (taille anormale).")
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
