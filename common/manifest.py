"""Contrôle d'intégrité des fichiers de paramétrage publiés par le portail TRANSCO-SAGE.

Le portail écrit dans `manifest.json` l'empreinte SHA-256 de chaque fichier publié.
Le batch la recalcule avant lecture : un fichier modifié après publication ou
tronqué pendant le transfert OPCON arrête le traitement (erreur fonctionnelle).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def verify_published_files(manifest_path: Path, files: list[Path]) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digests = {item["nom"]: item["sha256"] for item in manifest["fichiers"]}
    for path in files:
        expected = digests.get(path.name)
        if expected is None:
            raise ValueError(f"{path.name} absent du manifeste {manifest_path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(
                f"empreinte de {path.name} différente du manifeste {manifest_path} "
                f"(fichier modifié après publication ou transfert incomplet)"
            )
