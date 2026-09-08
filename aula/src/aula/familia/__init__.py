"""Familias, estudiantes y la asignación de un plan de estudios a cada uno."""

from aula.familia.modelo import (
    Adulto,
    Asignacion,
    Estudiante,
    Familia,
    ModoUI,
    PerfilVoz,
)
from aula.familia.almacen import cargar_familia, guardar_familia

__all__ = [
    "Adulto",
    "Asignacion",
    "Estudiante",
    "Familia",
    "ModoUI",
    "PerfilVoz",
    "cargar_familia",
    "guardar_familia",
]
