# IF-EFL-SAG-01 — Écritures comptables Efluid → Sage X3, toutes sociétés

> Batch unique des quatre sociétés Efluid (GEREDIS, SELIA, SEOLIS, SEOLISHA),
> décidé en atelier le 21/10/2026. Il remplace les anciennes interfaces
> IF-EFL-SAG-01 à 04, archivées dans `BATCHS/_archives/`. Depuis le 02/11/2026,
> la sortie suit le modèle d'import `EFLUID` créé par Inetum dans Sage X3.

Ce projet autonome transforme les fichiers IC Efluid quotidiens de chaque société
en fichiers d'import des pièces comptables Sage X3 (modèle `EFLUID`). Un seul code et une seule configuration servent toutes
les sociétés. Il a été créé à partir du starter kit SEOLIS et n'utilise que la
bibliothèque standard Python.

Référence : *Spécifications générales – Interface Efluid*, § 6.5 et § 7.4 à 7.9.

## Prérequis

- Python 3.10 ou supérieur
- aucune dépendance externe

## Exécution

```bash
cd /Users/marraillac/workspace/PRESTATIONS/SEOLIS/BATCHS/IF-EFL-SAG-01

# toutes les sociétés
python3.12 -m interfaces.if_efl_sag_01 \
  --input-dir /chemin/efluid \
  --output-dir /chemin/sage

# une ou plusieurs sociétés (un job OPCON par société, par exemple)
python3.12 -m interfaces.if_efl_sag_01 --societe GEREDIS \
  --input-dir /chemin/efluid --output-dir /chemin/sage \
  --reject-dir /chemin/rejets --log-dir /chemin/logs
```

`--societe` est répétable ; sans cette option, toutes les sociétés de la
configuration sont traitées. Les répertoires de rejets et de journaux sont
facultatifs : ils sont alors créés sous le répertoire de sortie. L'écrasement
d'un fichier déjà produit est refusé sauf avec `--overwrite`.

Chaque société reconnaît ses fichiers `<SOCIETE>CG<AAMMJJ>_<AAAAMMJJ>-<HHMMSS>.txt`
et produit :

```text
IF-EFL-SAG-01_GEREDISCG260429_20260430-000914.txt          fichier d'import Sage X3
reject/IF-EFL-SAG-01_GEREDISCG260429_20260430-000914.rejets.csv
logs/IF-EFL-SAG-01_<AAAAMMJJ_HHMMSS>.log             toutes sociétés
logs/IF-EFL-SAG-01_GEREDIS_<AAAAMMJJ_HHMMSS>.log     avec --societe GEREDIS
```

Le fichier à traiter est choisi par le préfixe de son nom (`GEREDIS*`,
`SELIA*`, `SEOLIS*`, `SEOLISHA*`), selon le motif `file_pattern` de chaque
société. Avec `--societe`, le journal porte le nom de la société : des jobs
OPCON lancés en parallèle, un par société, n'écrivent donc jamais dans le
même journal.

Le fichier des rejets comporte une colonne `societe`. Une société en erreur
(fichier d'une autre société, transcodification absente…) n'empêche pas le
traitement des autres ; le code retour global est le plus grave des codes.

## Sociétés

| Société | Fichier Efluid | Code société | Transcodification |
|---|---|---|---|
| GEREDIS | `GEREDISCG*.txt` | GE | GEREDIS |
| SELIA | `SELIACG*.txt` | SA | SELIA |
| SEOLIS | `SEOLISCG*.txt` | SO | SEOLIS |
| SEOLISHA | `SEOLISHACG*.txt` | SO | SEOLIS (`transco_societe`) |

Les sociétés sont déclarées dans `config/if_efl_sag_01.json`, section
`societes`. Les sections `efluid`, `rules` et `sage` sont communes ; une société
peut surcharger n'importe quelle valeur en ajoutant la même section dans son
entrée, par exemple :

```json
"SELIA": {
  "file_pattern": "^SELIACG...$",
  "company_code": "SA",
  "rules": {"accounting_date": "run_date"}
}
```

Ajouter une société = ajouter une entrée `societes` et ses lignes de
transcodification, sans modifier le code.

## Codes retour

| Code | Signification |
|---:|---|
| 0 | Succès |
| 1 | Avertissement : aucun fichier, fichier vide, lignes à montant nul ignorées |
| 2 | Succès partiel : au moins une pièce rejetée |
| 3 | Erreur fonctionnelle : configuration, encodage, fichier d'une autre société |
| 4 | Erreur technique : accès fichier, sortie déjà existante |

## Structure Sage X3 produite

Structure conforme au modèle d'import `EFLUID` paramétré par Inetum dans Sage X3
(objet `GAS`, fonction `GESGAS`, 44 champs ; relevé le 02/11/2026). Le champ `/` en
tête de chaque niveau du modèle correspond à l'indicateur G, D ou A :

```text
G;TYP;NUM;FCY;JOU;ACCDAT;CAT;STA;DESVCR;BPRVCR;REF;CUR;RATMLT;DACDIA
D;LIN;LEDTYP;FCYLIN;ACC;BPR;DES;SNS;AMTLED;AMTCUR;CSLBPR;FREREF;YREFEFLUID;TAX
A;ANALIN;LEDTYP;FCYLIN;DIE(0);CCE(0);DIE(1);CCE(1);DIE(2);CCE(2);DIE(3);CCE(3);AMTLED;AMTCUR;QTY;SNS
```

Paramètres du modèle : fichier à séparateur d'enregistrement, séparateur de champ
`;`, fin d'enregistrement CRLF (`\013\010`), jeu de caractères ISO-8859-1,
séparateur décimal `,`, dates `JJMMAAAA` (format standard SEOLIS, modèle EFLUID modifié
le 04/11/2026 ; `sage.date_format`).

Exemple :

```text
G;FACEF;;GE;VE;29042026;1;2;Efluid VE 29/04/2026;CG260429;;EUR;1;STDCO
D;1;1;GE;411110;;Facturation produit;1;120,00;120,00;HG;CG260429;CG260429;004
D;2;1;GE;706100;;Facturation produit;-1;120,00;120,00;HG;CG260429;CG260429;001
D;2;2;GE;706100;;Facturation produit;-1;120,00;120,00;;CG260429;CG260429;
A;1;2;GE;SCE;620;CHA;;CPA;9301101;MAR;;120,00;120,00;;-1
```

L'ordre des champs de chaque enregistrement est paramétré dans
`config/if_efl_sag_01.json` (`sage.fields`) et peut être aligné sur le modèle
définitif sans modifier le code.

## Règles appliquées

Règles validées en atelier le 21/10/2026, sauf mention contraire.

- **Pièces** : une pièce par société, journal (zone 3) et date d'opération ;
  elle regroupe tous les libellés du journal. Une ligne G par pièce, numéro
  `NUM` laissé à Sage.
- **Équilibre** : une pièce déséquilibrée est rejetée en totalité.
- **Rejet** : une ligne en anomalie (compte ou combinaison analytique absents de
  la transcodification, code taxe inconnu, format invalide) entraîne le rejet de
  toute sa pièce, donc de tout le journal du jour, pour ne jamais transmettre une
  pièce incomplète à Sage.
- **TYP** : `FACEF` si toutes les lignes de la pièce ont le libellé
  « Facturation produit », sinon `RECEF`.
- **DESVCR** (en-tête) : `rules.piece_description`, soit « Efluid <journal>
  <JJ/MM/AAAA> ». Chaque ligne D garde son libellé Efluid (zone 21).
- **ACCDAT** : date d'opération Efluid (zone 22). Valeur `run_date` possible
  pour utiliser la date du jour d'intégration.
- **Référence CAC** (zone 26, `CGAAMMJJ`) : dans le champ spécifique `YREFEFLUID`
  (« Code Efluid », ligne « Réf EFLUID » de la matrice Inetum) et dans `FREREF`
  sur toutes les lignes D, et en document origine `BPRVCR` sur l'en-tête (report
  en en-tête et doublon `FREREF` à confirmer).
- **Montants** : valeur absolue de la zone 18 convertie des centimes en décimal
  (`105103` → `1051,03`), sens porté par `SNS` (zone 17 : 1 / -1). Un signe
  incohérent avec le flag est rejeté.
- **Montant nul** : la ligne est ignorée et signalée (code retour 1).
- **ACC** : compte Agresso (zone 6) transcodifié via `transco/comptes.csv`.
- **Analytique** (`LEDTYP` 2) : comptes Sage de classes 2, 6, 7 et comptes
  467510, 467520, 467530, 443170, 443175. La ligne D est émise une seconde fois
  en `LEDTYP` 2 (sans partenaire ni taxe, comme dans le fichier type Sage), suivie
  d'une ligne A :
  - `CCE(0)` service et `CCE(2)` compte analytique : transcodification par
    compte, ANA3 (zone 9) et ANA5 (zone 11), obligatoire pour les classes 6 et 7 ;
  - `CCE(1)` chantier : ANA2 (zone 8) si le compte commence par 467 ;
  - `CCE(3)` marché : vide ;
  - `QTY` quantité : ANA2 (zone 8) pour les comptes Sage de
    `transco/comptes_quantite.csv` (443170, 443175), vide sinon.
- **TAX** : code taxe (zone 14) transcodifié via `transco/codes_taxe.csv`
  (`0` → `004`). Sur les journaux de trésorerie (`rules.treasury_journals` :
  RB, RE, RF, RI, RP, RV, RX), le code `0` donne un code taxe vide ; les autres
  codes restent transcodifiés.
- **Constantes** : `CAT` 1, `STA` 2 (pièce réelle), `CUR` EUR, `RATMLT` 1,
  `DACDIA` STDCO, `CSLBPR` HG ; libellés tronqués à 30 caractères.
- **Sortie** : ISO-8859-1, séparateur `;`, fins de ligne CRLF, virgule décimale,
  comme le paramètre le modèle `EFLUID` (`sage.encoding`, `sage.decimal_separator`).

## Transcodification

Le référentiel est géré par le métier dans l'application TRANSCO-SAGE (PHP,
PostgreSQL), qui publie trois fichiers ; le batch lit la version publiée,
déposée par OPCON sur le serveur batch :

- `comptes.csv` : une table unique, colonne `societe` en tête, puis
  `compte_ubw;compte_sage;ana1;ana3;ana5;service_sage;compte_ana_sage;libelle` ;
- `codes_taxe.csv` : `code_efluid;code_sage`, commun aux sociétés ;
- `comptes_quantite.csv` : `compte_sage;libelle`, comptes ouverts à la quantité.

Les chemins sont donnés par `transco.accounts`, `transco.taxes` et
`transco.quantity` (relatifs au projet, ou absolus vers le répertoire déposé).
Les fichiers de `transco/` sont la version initiale publiée par l'application.
Le moteur lit le référentiel via l'interface `TranscoSource`
(`interfaces/if_efl_sag_01/transco_source.py`), choisie par `transco.source`.

## Tests

```bash
python3.12 -m unittest discover -s tests -t . -v
```

Le test sur fichier réel utilise `../../EFluid_output_examples` s'il est présent.

## Points à confirmer

- report de la référence CAC en en-tête (`BPRVCR`), et maintien dans `FREREF`
  maintenant que `YREFEFLUID` la porte ;
- GEREDIS : 704313 / RAC / 9810103 et 704533 / PRE / 9352302 sans section
  service ni compte analytique Sage dans le classeur (pièce VE rejetée) ;
- liste complète des comptes ouverts à la quantité ;
- cadrage de l'interface PHP de gestion de la transcodification.
