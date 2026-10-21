"""Décodage du fichier IC Efluid et production des pièces Sage X3 (G / D / A)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from .model import AccountTransco, EfluidLine, Piece, Rejection, SageLine
from .transco_source import TranscoSource


@dataclass
class Stats:
    """Totaux de contrôle d'un fichier."""

    lines_read: int = 0
    zero_amount_skipped: int = 0
    pieces_written: int = 0
    pieces_rejected: int = 0
    lines_written: int = 0
    debit_cents: int = 0
    credit_cents: int = 0
    skipped_lines: list[int] = field(default_factory=list)


class Transco:
    """Tables de transcodification comptes / sections / codes taxe."""

    def __init__(self, accounts: list[AccountTransco], taxes: dict[str, str]) -> None:
        self.taxes = taxes
        self.by_account: dict[str, list[AccountTransco]] = {}
        for row in accounts:
            self.by_account.setdefault(row.ubw_account, []).append(row)

    @classmethod
    def load(cls, source: TranscoSource, societe: str) -> "Transco":
        accounts = source.accounts(societe)
        taxes = source.taxes()
        if not accounts:
            raise ValueError(f"table de transcodification des comptes vide pour la société {societe}")
        if not taxes:
            raise ValueError("table de transcodification des codes taxe vide")
        return cls(accounts, taxes)

    def sage_account(self, ubw_account: str) -> str:
        rows = self.by_account.get(ubw_account)
        if not rows:
            raise ValueError(f"compte {ubw_account} absent de la transcodification")
        targets = {row.sage_account for row in rows if row.sage_account}
        if not targets:
            raise ValueError(f"compte Sage non renseigné dans la transcodification pour {ubw_account}")
        if len(targets) > 1:
            raise ValueError(f"transcodification ambiguë pour le compte {ubw_account} : {sorted(targets)}")
        return targets.pop()

    def analytic_sections(self, line: EfluidLine, required: bool) -> tuple[str, str]:
        """Retourne (section service CCE(0), compte analytique CCE(2))."""
        rows = self.by_account.get(line.account, [])
        if required:
            rows = [row for row in rows if row.ana3 == line.ana3 and row.ana5 == line.ana5]
            if not rows:
                raise ValueError(
                    f"combinaison analytique absente de la transcodification "
                    f"(compte {line.account}, ANA3 {line.ana3 or '-'}, ANA5 {line.ana5 or '-'})"
                )
        pairs = {(row.service, row.analytic_account) for row in rows if row.service or row.analytic_account}
        if len(pairs) > 1:
            if required:
                raise ValueError(f"transcodification analytique ambiguë pour le compte {line.account} : {sorted(pairs)}")
            return "", ""
        service, analytic_account = pairs.pop() if pairs else ("", "")
        if required and not (service and analytic_account):
            raise ValueError(f"section service ou compte analytique Sage non renseigné pour le compte {line.account}")
        return service, analytic_account

    def tax(self, code: str) -> str:
        if not code:
            return ""
        if code not in self.taxes:
            raise ValueError(f"code taxe {code} absent de la transcodification")
        return self.taxes[code]


def extract(line: str, zone: dict[str, Any]) -> str:
    """Extrait une zone dont la position de début est exprimée en base 1."""
    start = int(zone["start"]) - 1
    return line[start : start + int(zone["length"])].strip()


def parse_line(number: int, raw: str, config: dict[str, Any]) -> EfluidLine:
    layout = config["efluid"]["layout"]
    values = {name: extract(raw, zone) for name, zone in layout.items()}
    return EfluidLine(line_number=number, raw=raw, **values)


def check_line(line: EfluidLine, config: dict[str, Any]) -> tuple[int, int]:
    """Contrôles de format ; retourne (sens, montant en centimes absolus)."""
    efluid = config["efluid"]
    errors = []
    if not line.journal or len(line.journal) > 5:
        errors.append("code journal absent ou supérieur à 5 caractères")
    if not line.account.isdigit():
        errors.append("compte Agresso absent ou non numérique")
    if line.currency != efluid["currency"]:
        errors.append(f"devise {line.currency or '-'} différente de {efluid['currency']}")
    if not line.label:
        errors.append("libellé d'écriture (zone 21) absent")
    try:
        datetime.strptime(line.operation_date, "%Y%m%d")
    except ValueError:
        errors.append("date d'opération (zone 22) invalide, format attendu AAAAMMJJ")
    direction = {"1": 1, "-1": -1}.get(line.direction)
    if direction is None:
        errors.append("flag débit/crédit (zone 17) différent de 1 / -1")
    try:
        amount = int(line.amount)
    except ValueError:
        errors.append("montant (zone 18) absent ou non numérique")
        amount = 0
    if direction and amount and (amount > 0) != (direction > 0):
        errors.append("signe du montant incohérent avec le flag débit/crédit")
    if errors:
        raise ValueError(" ; ".join(errors))
    return direction, abs(amount)


def starts_with(value: str, prefixes: list[str]) -> bool:
    return any(value.startswith(prefix) for prefix in prefixes)


def to_sage_line(line: EfluidLine, transco: Transco, config: dict[str, Any]) -> SageLine:
    rules = config["rules"]
    direction, cents = check_line(line, config)
    errors = []
    account = tax = ""
    try:
        account = transco.sage_account(line.account)
    except ValueError as error:
        errors.append(str(error))
    try:
        # Trésorerie : pas de code taxe pour les codes Efluid listés (0), au lieu de leur transcodification.
        untaxed = line.journal in rules["treasury_journals"] and line.tax_code in rules["treasury_untaxed_codes"]
        tax = "" if untaxed else transco.tax(line.tax_code)
    except ValueError as error:
        errors.append(str(error))
    analytic = bool(account) and (
        starts_with(account, rules["analytic_account_prefixes"]) or account in rules["analytic_accounts"]
    )
    service = analytic_account = ""
    if analytic:
        try:
            required = starts_with(line.account, rules["analytic_transco_required_prefixes"])
            service, analytic_account = transco.analytic_sections(line, required)
        except ValueError as error:
            errors.append(str(error))
    if errors:
        raise ValueError(" ; ".join(errors))
    return SageLine(
        source=line,
        account=account,
        direction=direction,
        cents=cents,
        tax=tax,
        analytic=analytic,
        service=service,
        chantier=line.ana2 if starts_with(line.account, rules["chantier_account_prefixes"]) else "",
        analytic_account=analytic_account,
        quantity=line.ana2 if account in rules["quantity_accounts"] else "",
    )


def format_amount(cents: int, config: dict[str, Any]) -> str:
    decimals = int(config["efluid"]["amount_implied_decimals"])
    text = f"{Decimal(cents).scaleb(-decimals):.{decimals}f}"
    return text.replace(".", config["sage"]["decimal_separator"])


def record(indicator: str, values: dict[str, str], config: dict[str, Any]) -> str:
    sage = config["sage"]
    try:
        fields = [values[name] for name in sage["fields"][indicator]]
    except KeyError as error:
        raise ValueError(f"champ Sage inconnu dans la configuration ({indicator}) : {error}") from error
    return sage["delimiter"].join([indicator, *fields])


def piece_records(piece_lines: list[SageLine], run_date: str, config: dict[str, Any]) -> list[str]:
    rules, sage = config["rules"], config["sage"]
    first = piece_lines[0].source
    # Une pièce regroupe plusieurs libellés Efluid : le libellé d'en-tête vient du journal et de la date.
    day = datetime.strptime(first.operation_date, "%Y%m%d")
    description = rules["piece_description"].format(journal=first.journal, date=f"{day:%d/%m/%Y}")
    description = description[: int(sage["description_max_length"])]
    invoice = all(line.source.label in rules["invoice_labels"] for line in piece_lines)
    cac_reference = first.cac_reference[: int(sage["free_reference_max_length"])]
    header = {
        "TYP": rules["invoice_piece_type"] if invoice else rules["other_piece_type"],
        "NUM": "",
        "FCY": first.company,
        "JOU": first.journal,
        "ACCDAT": first.operation_date if rules["accounting_date"] == "operation_date" else run_date,
        "CAT": rules["category"],
        "STA": rules["status"],
        "DES": description,
        "BPRVCR": first.cac_reference[: int(sage["origin_document_max_length"])],
        "REF": "",
        "CUR": config["efluid"]["currency"],
        "RATMTL": rules["rate"],
        "DACDIA": rules["transaction"],
    }
    output = [record("G", header, config)]
    for number, line in enumerate(piece_lines, start=1):
        amount = format_amount(line.cents, config)
        detail = {
            "LIN": str(number),
            "LEDTYP": "1",
            "IDTLIN": str(number),
            "FCYLIN": line.source.company,
            "ACC": line.account,
            "BPR": "",
            "DES": line.source.label[: int(sage["description_max_length"])],
            "SNS": str(line.direction),
            "AMTLED": amount,
            "AMTCUR": amount,
            "CSLBPR": rules["partner"],
            "FREREF": cac_reference,
            "TAX": line.tax,
        }
        output.append(record("D", detail, config))
        if not line.analytic:
            continue
        # Référentiel analytique : même ligne en LEDTYP 2, sans partenaire ni taxe (fichier type Sage).
        output.append(record("D", {**detail, "LEDTYP": "2", "CSLBPR": "", "TAX": ""}, config))
        analytic = {
            "ANALIN": "1",
            "LEDTYP": "2",
            "FCYLIN": line.source.company,
            "DIE(0)": sage["axis_service"],
            "CCE(0)": line.service,
            "DIE(1)": sage["axis_chantier"],
            "CCE(1)": line.chantier,
            "DIE(2)": sage["axis_analytic"],
            "CCE(2)": line.analytic_account,
            "DIE(3)": sage["axis_market"],
            "CCE(3)": "",
            "AMTLOC": amount,
            "AMTCUR": amount,
            "SNS": str(line.direction),
            "QTY": line.quantity,
        }
        output.append(record("A", analytic, config))
    return output


def group_pieces(lines: list[EfluidLine], key_fields: list[str]) -> list[Piece]:
    pieces: dict[tuple[str, ...], Piece] = {}
    for line in lines:
        key = tuple(getattr(line, name) for name in key_fields)
        pieces.setdefault(key, Piece(key)).lines.append(line)
    return list(pieces.values())


def reject_piece(piece: Piece, reasons: dict[int, str], default_reason: str) -> list[Rejection]:
    return [
        Rejection(line.line_number, line.journal, line.label, reasons.get(line.line_number, default_reason), line.raw)
        for line in piece.lines
    ]


def transform_lines(
    raw_lines: list[str], config: dict[str, Any], transco: Transco, run_date: str
) -> tuple[list[str], list[Rejection], Stats]:
    efluid, rules = config["efluid"], config["rules"]
    stats = Stats(lines_read=len(raw_lines))
    rejected: list[Rejection] = []
    parsed: list[EfluidLine] = []
    minimum = int(efluid["minimum_line_length"])
    for number, raw in enumerate(raw_lines, start=1):
        if len(raw) < minimum:
            rejected.append(Rejection(number, "", "", f"ligne inférieure à {minimum} caractères", raw))
            continue
        line = parse_line(number, raw, config)
        if line.company != efluid["company_code"]:
            raise ValueError(
                f"ligne {number} : code société {line.company or '-'} différent de {efluid['company_code']} "
                "(fichier d'une autre société ?)"
            )
        if rules["zero_amount_line"] == "skip" and line.amount.lstrip("-").strip("0") == "":
            stats.zero_amount_skipped += 1
            stats.skipped_lines.append(number)
            continue
        parsed.append(line)

    output: list[str] = []
    for piece in group_pieces(parsed, rules["piece_key"]):
        sage_lines: list[SageLine] = []
        errors: dict[int, str] = {}
        for line in piece.lines:
            try:
                sage_lines.append(to_sage_line(line, transco, config))
            except ValueError as error:
                errors[line.line_number] = str(error)
        if errors:
            numbers = ", ".join(str(n) for n in errors)
            rejected.extend(reject_piece(piece, errors, f"pièce rejetée : ligne(s) {numbers} en anomalie"))
            stats.pieces_rejected += 1
            continue
        balance = sum(line.direction * line.cents for line in sage_lines)
        if balance and rules["unbalanced_piece"] == "reject":
            reason = f"pièce déséquilibrée (solde {format_amount(abs(balance), config)} {'débiteur' if balance > 0 else 'créditeur'})"
            rejected.extend(reject_piece(piece, {}, reason))
            stats.pieces_rejected += 1
            continue
        output.extend(piece_records(sage_lines, run_date, config))
        stats.pieces_written += 1
        stats.lines_written += len(sage_lines)
        stats.debit_cents += sum(line.cents for line in sage_lines if line.direction > 0)
        stats.credit_cents += sum(line.cents for line in sage_lines if line.direction < 0)
    return output, sorted(rejected, key=lambda row: row.line_number), stats
