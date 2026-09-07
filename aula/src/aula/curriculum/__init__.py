"""Modelo canónico, validador y E/S del plan de estudios."""

from aula.curriculum.model import (
    Curriculum,
    Fuente,
    Licencia,
    Objetivo,
    Prioridad,
    TipoObjetivo,
)
from aula.curriculum.validator import Hallazgo, Severidad, validar

__all__ = [
    "Curriculum",
    "Fuente",
    "Hallazgo",
    "Licencia",
    "Objetivo",
    "Prioridad",
    "Severidad",
    "TipoObjetivo",
    "validar",
]
