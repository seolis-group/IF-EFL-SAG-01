"""Écriture atomique de fichiers texte."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def write_lines_atomic(
    destination: Path,
    lines: Iterable[str],
    *,
    encoding: str,
    newline: str,
    overwrite: bool,
) -> None:
    """Écrit toutes les lignes puis publie le fichier par renommage atomique."""
    destination = destination.resolve()
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Le fichier de sortie existe déjà : {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    if temporary.exists():
        temporary.unlink()

    try:
        with temporary.open("w", encoding=encoding, newline="") as stream:
            for line in lines:
                stream.write(line)
                stream.write(newline)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise

