"""Point d'entrée OPCON de l'interface IF-EFL-SAG-01 (toutes sociétés Efluid)."""

from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from common.atomic_writer import write_lines_atomic
from common.config import load_json
from common.logging_utils import configure_logger
from common.result import ExitCode
from .model import Rejection
from .societes import societe_config, societe_names
from .transco_source import TranscoSource, open_source
from .transform import Transco, format_amount, transform_lines

INTERFACE_ID = "IF-EFL-SAG-01"
ROOT = Path(__file__).parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"{INTERFACE_ID} - Écritures comptables Efluid → Sage X3")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--reject-dir", type=Path)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument(
        "--societe", action="append", dest="societes", metavar="SOCIETE",
        help="société à traiter (répétable) ; par défaut toutes les sociétés de la configuration",
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "if_efl_sag_01.json")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def discover_files(path: Path, pattern: re.Pattern[str]) -> list[Path]:
    return [item for item in sorted(path.iterdir(), key=lambda p: p.name) if item.is_file() and pattern.fullmatch(item.name)]


def write_rejections(path: Path, societe: str, source: str, rows: list[Rejection]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";", lineterminator="\r\n")
        writer.writerow(["interface", "societe", "fichier_source", "ligne", "journal", "libelle", "motif", "ligne_source"])
        for row in rows:
            writer.writerow([INTERFACE_ID, societe, source, row.line_number, row.journal, row.label, row.reason, row.raw_line.rstrip()])
    temporary.replace(path)


def process_file(source: Path, output_dir: Path, reject_dir: Path, config: dict[str, Any], transco: Transco, logger: Any, overwrite: bool) -> ExitCode:
    logger.info("Début du traitement | société=%s | source=%s", config["company_name"], source)
    raw_lines = [line for line in source.read_text(encoding=config["efluid"]["encoding"]).splitlines() if line.strip()]
    if not raw_lines:
        logger.warning("Fichier Efluid vide | source=%s", source)
        return ExitCode.WARNING
    output, rejections, stats = transform_lines(raw_lines, config, transco, datetime.now().strftime("%Y%m%d"))
    code = ExitCode.SUCCESS
    if stats.zero_amount_skipped:
        logger.warning("Lignes à montant nul ignorées | source=%s | lignes=%s", source.name, stats.skipped_lines)
        code = ExitCode.WARNING
    if output:
        target = output_dir / f"{INTERFACE_ID}_{source.stem}.txt"
        newline = "\r\n" if config["sage"]["line_ending"] == "CRLF" else "\n"
        write_lines_atomic(target, output, encoding=config["sage"]["encoding"], newline=newline, overwrite=overwrite)
        logger.info(
            "Fichier Sage généré | sortie=%s | modèle=%s | pièces=%d | lignes=%d | débit=%s | crédit=%s",
            target, config["sage"]["model"], stats.pieces_written, stats.lines_written,
            format_amount(stats.debit_cents, config), format_amount(stats.credit_cents, config),
        )
    else:
        logger.warning("Aucune pièce valide, aucun fichier Sage généré | source=%s", source)
        code = max(code, ExitCode.WARNING)
    if rejections:
        target = reject_dir / f"{INTERFACE_ID}_{source.stem}.rejets.csv"
        write_rejections(target, config["company_name"], source.name, rejections)
        for row in rejections:
            logger.error("Ligne rejetée | source=%s | ligne=%d | journal=%s | libellé=%s | motif=%s",
                         source.name, row.line_number, row.journal or "-", row.label or "-", row.reason)
        logger.error("Pièces rejetées | source=%s | pièces=%d | lignes=%d | rejets=%s",
                     source.name, stats.pieces_rejected, len(rejections), target)
        code = ExitCode.PARTIAL_REJECTS
    logger.info("Totaux de contrôle | source=%s | lignes_lues=%d | lignes_intégrées=%d | lignes_rejetées=%d | montants_nuls=%d",
                source.name, stats.lines_read, stats.lines_written, len(rejections), stats.zero_amount_skipped)
    return code


def process_societe(name: str, input_dir: Path, output_dir: Path, reject_dir: Path, config: dict[str, Any],
                    source: TranscoSource, logger: Any, overwrite: bool) -> ExitCode:
    effective = societe_config(config, name)
    pattern = re.compile(effective["efluid"]["file_pattern"])
    files = discover_files(input_dir, pattern)
    if not files:
        logger.warning("Aucun fichier Efluid trouvé | société=%s | répertoire=%s | motif=%s", name, input_dir, pattern.pattern)
        return ExitCode.WARNING
    transco = Transco.load(source, effective["transco_societe"])
    final = ExitCode.SUCCESS
    for path in files:
        try:
            final = max(final, process_file(path, output_dir, reject_dir, effective, transco, logger, overwrite))
        except (UnicodeError, ValueError) as error:
            logger.error("Erreur fonctionnelle | société=%s | source=%s | erreur=%s", name, path, error)
            final = max(final, ExitCode.FUNCTIONAL_ERROR)
        except OSError as error:
            logger.error("Erreur technique | société=%s | source=%s | erreur=%s", name, path, error)
            final = max(final, ExitCode.TECHNICAL_ERROR)
    return final


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir.resolve()
    reject_dir = (args.reject_dir or output_dir / "reject").resolve()
    log_dir = (args.log_dir or output_dir / "logs").resolve()
    # Un job OPCON par société peut tourner en parallèle : chaque job a son propre journal.
    scope = "".join(f"_{name}" for name in args.societes or [])
    logger = configure_logger(INTERFACE_ID, log_dir / f"{INTERFACE_ID}{scope}_{datetime.now():%Y%m%d_%H%M%S}.log")
    try:
        input_dir = args.input_dir.resolve(strict=True)
        if not input_dir.is_dir():
            raise NotADirectoryError(f"Répertoire d'entrée invalide : {input_dir}")
        config = load_json(args.config.resolve(strict=True))
        known = societe_names(config)
        selected = args.societes or known
        unknown = [name for name in selected if name not in known]
        if unknown:
            raise ValueError(f"société(s) inconnue(s) : {', '.join(unknown)} (connues : {', '.join(known)})")
        source = open_source(ROOT, config)
        final = ExitCode.SUCCESS
        for name in selected:
            try:
                code = process_societe(name, input_dir, output_dir, reject_dir, config, source, logger, args.overwrite)
            except (ValueError, UnicodeError, KeyError) as error:
                logger.error("Erreur de configuration ou de transcodification | société=%s | erreur=%s", name, error)
                code = ExitCode.FUNCTIONAL_ERROR
            except OSError as error:
                logger.error("Erreur technique | société=%s | erreur=%s", name, error)
                code = ExitCode.TECHNICAL_ERROR
            logger.info("Fin société | société=%s | code_retour=%d", name, code)
            final = max(final, code)
        logger.info("Fin du traitement | sociétés=%s | code_retour=%d", ",".join(selected), final)
        return int(final)
    except (ValueError, UnicodeError, KeyError) as error:
        logger.error("Erreur de configuration ou de format | erreur=%s", error)
        return int(ExitCode.FUNCTIONAL_ERROR)
    except OSError as error:
        logger.error("Erreur technique | erreur=%s", error)
        return int(ExitCode.TECHNICAL_ERROR)
