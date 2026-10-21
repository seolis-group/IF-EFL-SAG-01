"""Sources du référentiel de transcodification.

Le moteur ne connaît que l'interface `TranscoSource`. Le référentiel est
aujourd'hui porté par des fichiers CSV ; une table (Sage X3, base SEOLIS) pourra
le remplacer en ajoutant une implémentation et une valeur de `transco.source`,
sans modifier les règles de transformation.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Protocol

from .model import AccountTransco


class TranscoSource(Protocol):
    def accounts(self, societe: str) -> list[AccountTransco]:
        """Correspondances de comptes d'une société."""

    def taxes(self) -> dict[str, str]:
        """Correspondances code taxe Efluid → code taxe Sage, communes aux sociétés."""


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(stream, delimiter=";")]


class CsvTranscoSource:
    """Référentiel CSV : une table de comptes avec colonne `societe`, une table de codes taxe."""

    def __init__(self, accounts_path: Path, taxes_path: Path) -> None:
        self.accounts_path = accounts_path
        self.taxes_path = taxes_path

    def accounts(self, societe: str) -> list[AccountTransco]:
        return [
            AccountTransco(
                row["compte_ubw"], row["compte_sage"], row["ana1"], row["ana3"],
                row["ana5"], row["service_sage"], row["compte_ana_sage"],
            )
            for row in read_csv(self.accounts_path)
            if row["societe"] == societe
        ]

    def taxes(self) -> dict[str, str]:
        return {row["code_efluid"]: row["code_sage"] for row in read_csv(self.taxes_path)}


def open_source(base_dir: Path, config: dict[str, Any]) -> TranscoSource:
    settings = config["transco"]
    kind = settings.get("source", "csv")
    if kind == "csv":
        return CsvTranscoSource(base_dir / settings["accounts"], base_dir / settings["taxes"])
    raise ValueError(f"source de transcodification inconnue : {kind}")
