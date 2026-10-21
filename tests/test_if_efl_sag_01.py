from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from interfaces.if_efl_sag_01.cli import INTERFACE_ID, main
from interfaces.if_efl_sag_01.model import AccountTransco
from interfaces.if_efl_sag_01.societes import societe_config, societe_names
from interfaces.if_efl_sag_01.transco_source import CsvTranscoSource, open_source
from interfaces.if_efl_sag_01.transform import Transco, transform_lines

ROOT = Path(__file__).parents[1]
CONFIG_PATH = ROOT / "config" / "if_efl_sag_01.json"
BASE_CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
CONFIG = societe_config(BASE_CONFIG, "GEREDIS")
COMPANY = CONFIG["efluid"]["company_code"]
EXAMPLES = ROOT.parents[1] / "EFluid_output_examples"


def efluid_line(config: dict = CONFIG, **values: str) -> str:
    """Construit une ligne positionnelle de 2059 caractères à partir des zones nommées."""
    defaults = {
        "batch_number": f"{config['company_name']}20260429", "journal": "VE", "transaction_type": "GL",
        "company": config["efluid"]["company_code"], "currency": "EUR", "label": "Facturation produit",
        "operation_date": "20260429", "cac_reference": "CG260429", "tax_code": "0",
    }
    defaults.update(values)
    buffer = [" "] * 2059
    for name, value in defaults.items():
        zone = config["efluid"]["layout"][name]
        start = zone["start"] - 1
        buffer[start : start + zone["length"]] = value.ljust(zone["length"])[: zone["length"]]
    return "".join(buffer)


def balanced_file(directory: Path, societe: str, stamp: str = "260429_20260430-000914") -> Path:
    config = societe_config(BASE_CONFIG, societe)
    path = directory / f"{societe}CG{stamp}.txt"
    path.write_text("\n".join([
        efluid_line(config, journal="RE", label="Encaissement", account="411110", direction="-1", amount="-100"),
        efluid_line(config, journal="RE", label="Encaissement", account="411110", direction="1", amount="100"),
    ]) + "\n", encoding="ascii")
    return path


TRANSCO = Transco(
    [
        AccountTransco("411110", "411110", "", "", "", "", ""),
        AccountTransco("706100", "706100", "DCO", "GRD", "9825101", "620", "9301101"),
        AccountTransco("775000", "757000", "SLO", "GRD", "9841000", "899", "9411000"),
        AccountTransco("467510", "467510", "", "", "", "", ""),
        AccountTransco("443170", "443170", "", "", "", "", ""),
        AccountTransco("704850", "", "", "", "", "899", "9365200"),
    ],
    {"0": "004", "72": "001"},
)


def run(lines: list[str]):
    return transform_lines(lines, CONFIG, TRANSCO, "20260430")


class TransformTests(unittest.TestCase):
    def test_invoice_piece_with_analytic_line(self) -> None:
        output, rejected, stats = run([
            efluid_line(account="411110", direction="1", amount="12000"),
            efluid_line(account="706100", ana1="DCO", ana3="GRD", ana5="9825101", tax_code="72", direction="-1", amount="-12000"),
        ])
        self.assertEqual(rejected, [])
        self.assertEqual(output, [
            f"G;FACEF;;{COMPANY};VE;20260429;1;2;Efluid VE 29/04/2026;CG260429;;EUR;1;STDCO",
            f"D;1;1;1;{COMPANY};411110;;Facturation produit;1;120.00;120.00;HG;CG260429;004",
            f"D;2;1;2;{COMPANY};706100;;Facturation produit;-1;120.00;120.00;HG;CG260429;001",
            f"D;2;2;2;{COMPANY};706100;;Facturation produit;-1;120.00;120.00;;CG260429;",
            f"A;1;2;{COMPANY};SCE;620;CHA;;CPA;9301101;MAR;;120.00;120.00;-1;",
        ])
        self.assertEqual((stats.pieces_written, stats.debit_cents, stats.credit_cents), (1, 12000, 12000))

    def test_account_is_transcoded(self) -> None:
        output, rejected, _ = run([
            efluid_line(journal="RX", label="Provision", account="411110", direction="1", amount="500"),
            efluid_line(journal="RX", label="Provision", account="775000", ana3="GRD", ana5="9841000", direction="-1", amount="-500"),
        ])
        self.assertEqual(rejected, [])
        self.assertTrue(output[0].startswith("G;RECEF;"))
        self.assertIn(";757000;", output[2])
        self.assertEqual(output[4], f"A;1;2;{COMPANY};SCE;899;CHA;;CPA;9411000;MAR;;5.00;5.00;-1;")

    def test_chantier_section_for_467_accounts(self) -> None:
        output, rejected, _ = run([
            efluid_line(journal="RE", label="Encaissement", account="411110", direction="-1", amount="-300"),
            efluid_line(journal="RE", label="Encaissement", account="467510", ana2="20065502", direction="1", amount="300"),
        ])
        self.assertEqual(rejected, [])
        self.assertEqual(output[-1], f"A;1;2;{COMPANY};SCE;;CHA;20065502;CPA;;MAR;;3.00;3.00;1;")

    def test_quantity_for_accounts_open_to_quantity(self) -> None:
        output, rejected, _ = run([
            efluid_line(journal="RE", label="Encaissement", account="411110", direction="-1", amount="-300"),
            efluid_line(journal="RE", label="Encaissement", account="443170", ana2="1250", direction="1", amount="300"),
        ])
        self.assertEqual(rejected, [])
        self.assertEqual(output[-1], f"A;1;2;{COMPANY};SCE;;CHA;;CPA;;MAR;;3.00;3.00;1;1250")

    def test_treasury_lines_have_no_tax_for_code_zero(self) -> None:
        output, rejected, _ = run([
            efluid_line(journal="RE", label="Encaissement", account="411110", tax_code="0", direction="-1", amount="-300"),
            efluid_line(journal="RE", label="Encaissement", account="411110", tax_code="72", direction="1", amount="300"),
        ])
        self.assertEqual(rejected, [])
        self.assertEqual([line.split(";")[-1] for line in output if line.startswith("D;")], ["", "001"])

    def test_missing_analytic_transco_rejects_whole_piece(self) -> None:
        output, rejected, stats = run([
            efluid_line(account="411110", direction="1", amount="100"),
            efluid_line(account="706100", ana3="RAC", ana5="0000000", direction="-1", amount="-100"),
        ])
        self.assertEqual(output, [])
        self.assertEqual([row.line_number for row in rejected], [1, 2])
        self.assertIn("combinaison analytique absente", rejected[1].reason)
        self.assertIn("ligne(s) 2", rejected[0].reason)
        self.assertEqual(stats.pieces_rejected, 1)

    def test_empty_sage_account_is_rejected(self) -> None:
        _, rejected, _ = run([
            efluid_line(account="411110", direction="1", amount="100"),
            efluid_line(account="704850", direction="-1", amount="-100"),
        ])
        self.assertIn("compte Sage non renseigné", rejected[1].reason)

    def test_unbalanced_piece_is_rejected(self) -> None:
        output, rejected, _ = run([
            efluid_line(journal="RE", label="Reaffectation", account="411110", direction="1", amount="840"),
        ])
        self.assertEqual(output, [])
        self.assertIn("pièce déséquilibrée", rejected[0].reason)

    def test_one_piece_per_journal_whatever_the_labels(self) -> None:
        output, rejected, stats = run([
            efluid_line(journal="RE", label="Reaffectation", account="411110", direction="-1", amount="-84067"),
            efluid_line(journal="RP", label="Encaissement", account="411110", direction="-1", amount="-200"),
            efluid_line(journal="RE", label="Annulation reaffectation", account="411110", direction="1", amount="17600"),
            efluid_line(journal="RE", label="Annulation reaffectation", account="411110", direction="1", amount="66467"),
            efluid_line(journal="RP", label="Encaissement", account="411110", direction="1", amount="200"),
        ])
        self.assertEqual((rejected, stats.pieces_written), ([], 2))
        headers = [line.split(";") for line in output if line.startswith("G;")]
        self.assertEqual([(h[4], h[8]) for h in headers], [("RE", "Efluid RE 29/04/2026"), ("RP", "Efluid RP 29/04/2026")])
        self.assertIn("Annulation reaffectation", [line.split(";")[7] for line in output if line.startswith("D;")])

    def test_piece_type_is_invoice_only_when_all_labels_are_invoices(self) -> None:
        output, _, _ = run([
            efluid_line(account="411110", direction="1", amount="100"),
            efluid_line(label="Avoir", account="411110", direction="-1", amount="-100"),
        ])
        self.assertTrue(output[0].startswith("G;RECEF;"))

    def test_zero_amount_lines_are_skipped(self) -> None:
        output, rejected, stats = run([efluid_line(journal="RX", label="Compensation", account="411110", direction="-1", amount="0")])
        self.assertEqual((output, rejected, stats.zero_amount_skipped), ([], [], 1))

    def test_sign_inconsistent_with_flag_is_rejected(self) -> None:
        _, rejected, _ = run([
            efluid_line(account="411110", direction="1", amount="-100"),
            efluid_line(account="411110", direction="-1", amount="-100"),
        ])
        self.assertIn("signe du montant incohérent", rejected[0].reason)

    def test_other_company_file_is_a_functional_error(self) -> None:
        with self.assertRaises(ValueError):
            run([efluid_line(company="XX", account="411110", direction="1", amount="100")])

    def test_short_line_is_rejected(self) -> None:
        _, rejected, _ = run(["TROP COURT"])
        self.assertIn("inférieure à", rejected[0].reason)


class SocieteConfigTests(unittest.TestCase):
    def test_all_efluid_companies_are_configured(self) -> None:
        self.assertEqual(societe_names(BASE_CONFIG), ["GEREDIS", "SELIA", "SEOLIS", "SEOLISHA"])

    def test_effective_config_sets_company_settings(self) -> None:
        selia = societe_config(BASE_CONFIG, "SELIA")
        self.assertEqual(selia["company_name"], "SELIA")
        self.assertEqual(selia["efluid"]["company_code"], "SA")
        self.assertTrue(selia["efluid"]["file_pattern"].startswith("^SELIACG"))
        self.assertEqual(selia["transco_societe"], "SELIA")
        self.assertNotIn("societes", selia)

    def test_seolisha_uses_seolis_transco(self) -> None:
        self.assertEqual(societe_config(BASE_CONFIG, "SEOLISHA")["transco_societe"], "SEOLIS")

    def test_company_can_override_a_common_rule(self) -> None:
        config = json.loads(json.dumps(BASE_CONFIG))
        config["societes"]["SELIA"]["rules"] = {"accounting_date": "run_date"}
        selia = societe_config(config, "SELIA")
        self.assertEqual(selia["rules"]["accounting_date"], "run_date")
        self.assertEqual(selia["rules"]["piece_key"], BASE_CONFIG["rules"]["piece_key"])
        self.assertEqual(societe_config(config, "GEREDIS")["rules"]["accounting_date"], "operation_date")

    def test_unknown_company_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            societe_config(BASE_CONFIG, "INCONNUE")


class TranscoSourceTests(unittest.TestCase):
    def test_accounts_are_filtered_by_company(self) -> None:
        source = open_source(ROOT, BASE_CONFIG)
        geredis = Transco.load(source, "GEREDIS")
        selia = Transco.load(source, "SELIA")
        self.assertGreater(len(geredis.by_account), 20)
        self.assertGreater(len(selia.by_account), 20)
        self.assertNotEqual(geredis.by_account.keys(), selia.by_account.keys())
        self.assertEqual(geredis.tax("72"), "001")

    def test_company_without_accounts_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Transco.load(open_source(ROOT, BASE_CONFIG), "SEOLISHA")

    def test_csv_source_reads_company_column(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "comptes.csv").write_text(
                "societe;compte_ubw;compte_sage;ana1;ana3;ana5;service_sage;compte_ana_sage;libelle\n"
                "A;411110;411111;;;;;;CLIENTS\nB;411110;411112;;;;;;CLIENTS\n", encoding="utf-8")
            (root / "taxes.csv").write_text("code_efluid;code_sage\n0;004\n", encoding="utf-8")
            source = CsvTranscoSource(root / "comptes.csv", root / "taxes.csv")
            self.assertEqual([row.sage_account for row in source.accounts("B")], ["411112"])

    def test_unknown_source_type_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            open_source(ROOT, {"transco": {"source": "x3"}})


class CliTests(unittest.TestCase):
    def arguments(self, root: Path, *extra: str) -> list[str]:
        return ["--input-dir", str(root / "in"), "--output-dir", str(root / "out"), "--config", str(CONFIG_PATH), *extra]

    def test_end_to_end_all_companies_and_overwrite_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "in").mkdir()
            sources = [balanced_file(root / "in", name) for name in ("GEREDIS", "SELIA", "SEOLIS", "SEOLISHA")]
            self.assertEqual(main(self.arguments(root)), 0)
            for source in sources:
                target = root / "out" / f"{INTERFACE_ID}_{source.stem}.txt"
                self.assertTrue(target.read_bytes().endswith(b"\r\n"), target)
            self.assertEqual(main(self.arguments(root)), 4)

    def test_company_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "in").mkdir()
            balanced_file(root / "in", "GEREDIS")
            balanced_file(root / "in", "SELIA")
            self.assertEqual(main(self.arguments(root, "--societe", "SELIA")), 0)
            self.assertEqual([path.name for path in (root / "out").glob("*.txt")], [f"{INTERFACE_ID}_SELIACG260429_20260430-000914.txt"])

    def test_parallel_jobs_have_their_own_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "in").mkdir()
            balanced_file(root / "in", "GEREDIS")
            balanced_file(root / "in", "SELIA")
            self.assertEqual(main(self.arguments(root, "--societe", "GEREDIS")), 0)
            self.assertEqual(main(self.arguments(root, "--societe", "SELIA")), 0)
            logs = sorted(path.name.rsplit("_", 2)[0] for path in (root / "out" / "logs").glob("*.log"))
            self.assertEqual(logs, [f"{INTERFACE_ID}_GEREDIS", f"{INTERFACE_ID}_SELIA"])

    def test_unknown_company_argument_is_a_functional_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "in").mkdir()
            self.assertEqual(main(self.arguments(root, "--societe", "INCONNUE")), 3)

    def test_company_in_error_does_not_block_the_others(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "in").mkdir()
            balanced_file(root / "in", "SELIA")
            wrong = balanced_file(root / "in", "GEREDIS")
            wrong.write_text(efluid_line(company="SA", account="411110", direction="1", amount="100") + "\n", encoding="ascii")
            self.assertEqual(main(self.arguments(root)), 3)
            self.assertTrue((root / "out" / f"{INTERFACE_ID}_SELIACG260429_20260430-000914.txt").exists())

    def test_no_file_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "in").mkdir()
            self.assertEqual(main(self.arguments(root)), 1)


@unittest.skipUnless(EXAMPLES.is_dir(), "exemples Efluid non disponibles")
class RealExampleTests(unittest.TestCase):
    def test_real_examples_are_processed(self) -> None:
        source = open_source(ROOT, BASE_CONFIG)
        for name in societe_names(BASE_CONFIG):
            with self.subTest(societe=name):
                config = societe_config(BASE_CONFIG, name)
                files = sorted(EXAMPLES.glob(f"{name}CG*.txt"))
                self.assertEqual(len(files), 1)
                lines = [line for line in files[0].read_text(encoding="ascii").splitlines() if line.strip()]
                transco = Transco.load(source, config["transco_societe"])
                output, rejected, stats = transform_lines(lines, config, transco, "20260430")
                self.assertGreater(stats.pieces_written, 0)
                self.assertEqual(stats.debit_cents, stats.credit_cents)
                self.assertEqual(stats.lines_written + len(rejected) + stats.zero_amount_skipped, stats.lines_read)


if __name__ == "__main__":
    unittest.main()
