# -*- coding: utf-8 -*-
"""Publie une nouvelle version de Dofus Manager (Windows + macOS).

    python tools/release.py 4.7 notes.md

1. vérifie que le dépôt est propre, sur main et à jour ;
2. met APP_VERSION = "4.7" dans dm_core.py et commite « v4.7 » ;
3. crée le tag annoté v4.7, dont le message est le contenu de notes.md ;
4. pousse main et le tag.

GitHub Actions (.github/workflows/release.yml) compile alors l'exe Windows et le dmg macOS
depuis ce même commit et les publie ensemble dans la release v4.7, avec notes.md en
description. Suivi : onglet « Actions » du dépôt.
"""
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import version as ver  # noqa: E402

ROOT = ver.ROOT


def git(*args, capture=False):
    r = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=capture)
    if r.returncode != 0:
        sys.exit(f"git {' '.join(args)} a échoué" + (f" :\n{r.stderr.strip()}" if capture else ""))
    return r.stdout.strip() if capture else None


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    new, notes_path = ver.validate(sys.argv[1].removeprefix("v")), pathlib.Path(sys.argv[2])
    tag = f"v{new}"
    notes = notes_path.read_text(encoding="utf-8").strip() if notes_path.exists() else ""
    if not notes:
        sys.exit(f"Notes de version vides ou introuvables : {notes_path}")

    if git("status", "--porcelain", "--untracked-files=no", capture=True):
        sys.exit("Des modifications ne sont pas commitées : commitez-les d'abord.")
    if git("rev-parse", "--abbrev-ref", "HEAD", capture=True) != "main":
        sys.exit("Une release se fait depuis la branche main.")
    git("fetch", "--quiet", "--tags", "origin")
    if git("rev-parse", "HEAD", capture=True) != git("rev-parse", "origin/main", capture=True):
        sys.exit("main n'est pas identique à origin/main : faites git pull / git push d'abord.")
    if git("tag", "-l", tag, capture=True):
        sys.exit(f"Le tag {tag} existe déjà.")
    old = ver.get()
    if ver.win_tuple(new) <= ver.win_tuple(old):
        sys.exit(f"{new} n'est pas supérieure à la version actuelle {old}.")

    ver.set_version(new)
    git("commit", "--quiet", "-m", tag, "--", "dm_core.py")
    git("tag", "-a", tag, "-F", str(notes_path.resolve()))
    git("push", "--quiet", "--atomic", "origin", "main", tag)
    print(f"{tag} poussé ({old} -> {new}). GitHub Actions compile Windows + macOS et publie la release.")


if __name__ == "__main__":
    main()
