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

from common.manifest import verify_published_files

from .model import AccountTransco


class TranscoSource(Protocol):
    def accounts(self, societe: str) -> list[AccountTransco]:
        """Correspondances de comptes d'une société."""

    def taxes(self) -> dict[tuple[str, str], str]:
        """Correspondances (code taxe Efluid, compte Sage) → code taxe Sage, communes aux sociétés.
        Compte vide : code valable pour tous les comptes sans ligne propre."""

    def analytic_rules(self) -> dict[str, frozenset[str]]:
        """Comptes Sage par règle analytique Efluid (CCE(1), QTY), communs aux sociétés."""


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(stream, delimiter=";")]


class CsvTranscoSource:
    """Référentiel CSV publié par le portail Atterri'Sage : correspondances UBW → Sage
    communes aux batchs (colonne `societe`), codes taxe et règles analytiques Efluid."""

    def __init__(self, accounts_path: Path, taxes_path: Path, rules_path: Path) -> None:
        self.accounts_path = accounts_path
        self.taxes_path = taxes_path
        self.rules_path = rules_path

    def accounts(self, societe: str) -> list[AccountTransco]:
        return [
            AccountTransco(
                row["compte_ubw"], row["compte_sage"], row["ana1"], row["ana3"],
                row["ana5"], row["service_sage"], row["compte_ana_sage"],
            )
            for row in read_csv(self.accounts_path)
            if row["societe"] == societe
        ]

    def taxes(self) -> dict[tuple[str, str], str]:
        # La colonne compte_sage est facultative : un fichier publié avant son ajout reste lisible.
        return {(row["code_efluid"], row.get("compte_sage", "")): row["code_sage"] for row in read_csv(self.taxes_path)}

    def analytic_rules(self) -> dict[str, frozenset[str]]:
        rules: dict[str, set[str]] = {}
        for row in read_csv(self.rules_path):
            rules.setdefault(row["regle"], set()).add(row["compte_sage"])
        return {rule: frozenset(accounts) for rule, accounts in rules.items()}


def open_source(base_dir: Path, config: dict[str, Any]) -> TranscoSource:
    settings = config["transco"]
    kind = settings.get("source", "csv")
    if kind == "csv":
        accounts, taxes, rules = (base_dir / settings[name] for name in ("accounts", "taxes", "analytic_rules"))
        if settings.get("manifest"):
            verify_published_files(base_dir / settings["manifest"], [accounts, taxes, rules])
        return CsvTranscoSource(accounts, taxes, rules)
    raise ValueError(f"source de transcodification inconnue : {kind}")
