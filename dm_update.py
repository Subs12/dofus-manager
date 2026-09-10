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
    try:
        r = subprocess.run([_GH, *args], capture_output=capture_stdout, text=True,
                          timeout=timeout, creationflags=_CREATE_NO_WINDOW)
        return r.stdout if (r.returncode == 0 and capture_stdout) else ("" if r.returncode == 0 else None)
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
    return found[0]


def install_and_restart(new_exe_path):
    """Remplace l'exe courant par le nouveau et relance l'application.

    L'exe en cours d'exécution est verrouillé par Windows : impossible de
    l'écraser directement. On délègue le remplacement à un script batch qui
    attend la fin du process courant, copie le nouvel exe, le relance, puis
    s'auto-supprime.
    """
    current = pathlib.Path(sys.executable)
    pid = os.getpid()
    bat = pathlib.Path(tempfile.gettempdir()) / f"dofusmanager_update_{pid}.bat"
    bat.write_text(
        "@echo off\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        f'copy /y "{new_exe_path}" "{current}" >nul\r\n'
        f'start "" "{current}"\r\n'
        f'del "{new_exe_path}"\r\n'
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=_CREATE_NO_WINDOW,
                     close_fds=True, cwd=tempfile.gettempdir())
    core.log.info("Mise à jour : redémarrage vers %s", new_exe_path)
