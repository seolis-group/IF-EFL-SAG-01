"""Configuration effective d'une société.

La configuration commune (`efluid`, `rules`, `sage`, `transco`) s'applique à
toutes les sociétés. Chaque entrée de `societes` fixe le motif de nom de fichier
et le code société attendus, et peut surcharger n'importe quelle valeur commune
dans ses propres sections `efluid`, `rules` ou `sage`.
"""

from __future__ import annotations

import copy
from typing import Any

OVERRIDABLE_SECTIONS = ("efluid", "rules", "sage")


def merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def societe_names(config: dict[str, Any]) -> list[str]:
    return list(config["societes"])


def societe_config(config: dict[str, Any], name: str) -> dict[str, Any]:
    try:
        settings = config["societes"][name]
    except KeyError as error:
        raise ValueError(f"société inconnue dans la configuration : {name}") from error
    effective = {key: copy.deepcopy(value) for key, value in config.items() if key != "societes"}
    for section in OVERRIDABLE_SECTIONS:
        if section in settings:
            effective[section] = merge(effective[section], settings[section])
    effective["company_name"] = name
    effective["efluid"]["file_pattern"] = settings["file_pattern"]
    effective["efluid"]["company_code"] = settings["company_code"]
    effective["transco_societe"] = settings.get("transco_societe", name)
    return effective
