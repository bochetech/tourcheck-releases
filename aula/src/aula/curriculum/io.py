"""Lectura y escritura del currículo en YAML.

El currículo vive en git como YAML por una razón concreta: cuando algo chirríe,
un diff legible te dice qué cambió y puedes corregirlo a mano en treinta
segundos. Nunca es un requisito para empezar, pero sí la red de seguridad.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

import yaml

from aula.curriculum.model import Curriculum


def cargar(ruta: str | Path) -> Curriculum:
    """Carga un currículo desde un archivo YAML."""
    ruta = Path(ruta)
    with ruta.open(encoding="utf-8") as fh:
        datos = yaml.safe_load(fh) or {}
    if not isinstance(datos, dict):
        raise ValueError(f"{ruta}: se esperaba un mapa YAML en la raíz")
    return Curriculum.model_validate(datos)


def _limpiar(valor: Any) -> Any:
    """Quita nulos y colecciones vacías para que el YAML sea legible en un diff."""
    if isinstance(valor, dict):
        return {k: _limpiar(v) for k, v in valor.items() if v not in (None, [], {})}
    if isinstance(valor, list):
        return [_limpiar(v) for v in valor]
    if isinstance(valor, _dt.date):
        return valor.isoformat()
    return valor


def guardar(curriculum: Curriculum, ruta: str | Path) -> Path:
    """Escribe el currículo como YAML estable y diffeable."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    datos = _limpiar(curriculum.model_dump(mode="json"))
    with ruta.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            datos,
            fh,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=100,
        )
    return ruta
