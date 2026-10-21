"""Codes retour communs pour l'ordonnanceur."""

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    WARNING = 1
    PARTIAL_REJECTS = 2
    FUNCTIONAL_ERROR = 3
    TECHNICAL_ERROR = 4

