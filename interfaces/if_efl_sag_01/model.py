"""Objets métier de l'interface."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EfluidLine:
    """Ligne d'écriture du fichier IC Efluid, zones utiles décodées."""

    line_number: int
    raw: str
    batch_number: str
    journal: str
    transaction_type: str
    company: str
    account: str
    ana1: str
    ana2: str
    ana3: str
    ana5: str
    tax_code: str
    currency: str
    direction: str
    amount: str
    label: str
    operation_date: str
    cac_reference: str


@dataclass(frozen=True)
class AccountTransco:
    """Correspondance UBW → Sage X3 issue du classeur DOC-02."""

    ubw_account: str
    sage_account: str
    ana1: str
    ana3: str
    ana5: str
    service: str
    analytic_account: str


@dataclass
class SageLine:
    """Ligne d'écriture transcodée, prête à être écrite en D (et A)."""

    source: EfluidLine
    account: str
    direction: int
    cents: int
    tax: str
    analytic: bool
    service: str = ""
    chantier: str = ""
    analytic_account: str = ""
    quantity: str = ""


@dataclass
class Piece:
    """Pièce comptable Sage X3 : une ligne G et ses lignes D/A."""

    key: tuple[str, ...]
    lines: list[EfluidLine] = field(default_factory=list)


@dataclass(frozen=True)
class Rejection:
    line_number: int
    journal: str
    label: str
    reason: str
    raw_line: str
