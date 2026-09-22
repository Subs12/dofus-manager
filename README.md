# Dofus Manager

Gestionnaire de fenêtres multi-comptes pour **Dofus 3**, sur **Windows** et **macOS**.
Passez d'un personnage à l'autre avec une touche ou un bouton de souris, dans l'ordre de votre équipe.

> Dofus Manager utilise uniquement les fonctions de fenêtrage du système : il ne lit pas et ne modifie pas
> la mémoire du jeu, n'injecte rien et n'automatise aucune action en jeu.

## Téléchargement

Prenez la dernière version sur la page **[Releases](https://github.com/Subs12/dofus-manager/releases/latest)** :

| Système | Fichier |
|---|---|
| Windows 10 / 11 | `DofusManager-<version>-windows.exe` |
| macOS 11 ou plus récent (puces Apple M1, M2, M3…) | `DofusManager-<version>-macos.dmg` |

Les deux fichiers d'une même release sont compilés depuis le même code et portent le même numéro de version.
Une fois installé, Dofus Manager vous prévient lui-même des nouvelles versions et s'installe en un clic.

## Fonctionnalités

- **Détection automatique** des fenêtres Dofus ouvertes, avec le nom, la classe et le portrait de chaque personnage.
- **Cyclage** : personnage suivant ou précédent avec une touche ou un bouton de souris, même quand le jeu a le focus.
- **Accès direct** : une touche pour une position du cycle ou pour un personnage précis.
- **Boutons de souris** : boutons 4 et 5, clic molette (et boutons supplémentaires des souris gaming sur Mac), sans logiciel constructeur.
- **Presets** : enregistrez vos équipes et appliquez-les en un clic ou avec un raccourci.
- **Disposition** : tout en plein écran, mosaïque, ou un personnage par écran.
- **Bandeau** discret en haut de l'écran à chaque changement de personnage.
- **Statistiques** : temps passé et nombre de passages par personnage.
- Thème clair ou sombre, icône dans la zone de notification (Windows) ou la barre des menus (Mac), lancement à l'ouverture de session.

## Installation

### Windows

1. Téléchargez `DofusManager-<version>-windows.exe` et lancez-le. Aucune installation n'est nécessaire.
2. Si Windows affiche « Windows a protégé votre ordinateur », cliquez sur **Informations complémentaires**, puis **Exécuter quand même**.

### macOS

1. Ouvrez `DofusManager-<version>-macos.dmg` et glissez **Dofus Manager** dans le dossier **Applications**.
2. **Première ouverture** : l'application n'est pas signée par un développeur Apple, donc macOS la bloque la première fois.
   Ouvrez-la une fois, puis allez dans **Réglages Système › Confidentialité et sécurité** et cliquez sur **Ouvrir quand même**.
3. **Autorisation Accessibilité** (obligatoire) : au premier lancement, macOS propose d'ouvrir les réglages.
   Activez **Dofus Manager** dans **Réglages Système › Confidentialité et sécurité › Accessibilité**.
   Sans elle, l'application ne voit pas les fenêtres du jeu et les raccourcis ne marchent pas.
   L'application la détecte seule en quelques secondes, sans redémarrage.

> **Important sur Mac**
> - Lancez l'application depuis **Applications**, pas depuis le Bureau ou Documents : quand ces dossiers sont
>   synchronisés par iCloud, macOS n'arrive pas à reconnaître l'application et refuse l'autorisation.
> - Après une mise à jour, macOS peut redemander l'autorisation Accessibilité. Si les personnages n'apparaissent
>   plus, retirez **Dofus Manager** de la liste Accessibilité (bouton **−**) puis réactivez-le.

## Utilisation

1. Lancez vos comptes Dofus : ils apparaissent dans la page **Personnages**.
2. Ajoutez-les au cycle dans l'ordre voulu (glisser-déposer pour réordonner), puis cliquez sur **Activer le cyclage**.
3. Changez de personnage avec vos raccourcis. Par défaut :

| | Windows | macOS |
|---|---|---|
| Personnage suivant | `F23` | `Souris 5` |
| Personnage précédent | `F21` | `Souris 4` |

Tout se modifie dans la page **Raccourcis** : cliquez sur **Modifier**, puis appuyez sur la touche ou le bouton de souris.
Le bouton **Pause** libère les raccourcis, par exemple pour écrire dans le chat.

### Différences entre Windows et macOS

| | Windows | macOS |
|---|---|---|
| Passer au personnage dont c'est le tour | ✅ | ❌ (macOS ne permet pas de le détecter) |
| Boutons de souris au-delà de 4 et 5 | ❌ | ✅ |
| Autorisation à accorder | aucune | Accessibilité |

## Données

Les réglages, presets, statistiques et le journal (`app.log`) sont dans le dossier `.dofus_manager` de votre dossier
utilisateur. Le bouton **Paramètres › Ouvrir le dossier** l'ouvre directement.

---

## Développement

Le code est en Python (CustomTkinter). Une seule base de code pour les deux systèmes :

| Fichier | Rôle |
|---|---|
| `dofus_manager.py` | point d'entrée : fenêtre principale, navigation, icône de notification |
| `dm_pages.py`, `dm_widgets.py` | pages et composants de l'interface |
| `dm_core.py` | logique commune : configuration, cycle, presets, statistiques, **numéro de version** |
| `dm_win.py` | couche Windows (API Win32) |
| `dm_mac.py` | couche macOS (Accessibility, event tap Quartz) |
| `dm_update.py` | vérification et installation des mises à jour (releases GitHub) |

### Compiler

| | Commande | Résultat |
|---|---|---|
| Windows (Python 3.13) | `.\build.ps1` | `dist\DofusManager-<version>-windows.exe` |
| macOS (Python de python.org) | `./build_mac.sh` | `dist/DofusManager-<version>-macos.dmg` |

Les scripts créent leur propre environnement Python (`.venv-win`, `.venv`) et installent les dépendances
(`requirements-win.txt`, `requirements-mac.txt`).

### Version et publication

Le numéro de version n'est écrit qu'**à un seul endroit** : `APP_VERSION` dans `dm_core.py`.
L'exe, le .app, les noms des fichiers et le tag git en sont tous dérivés, et chaque compilation vérifie que
la version inscrite dans le fichier produit correspond. Pour publier une version :

```bash
python tools/release.py 4.7 notes.md     # notes.md : les nouveautés, affichées dans la release
```

Ce script passe `APP_VERSION` à 4.7, commite, crée le tag `v4.7` et pousse. GitHub Actions
([`.github/workflows/release.yml`](.github/workflows/release.yml)) compile alors l'exe sur Windows et le dmg
sur macOS depuis ce même commit, puis publie les deux dans la release `v4.7`. Suivi dans l'onglet **Actions**.
Chaque pull request est aussi compilée pour les deux systèmes, sans rien publier.

---

© 2026 Subs12. Tous droits réservés. Les illustrations de classes sont la propriété d'Ankama.
