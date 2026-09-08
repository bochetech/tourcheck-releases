"""Guardar y leer la familia. YAML por ahora; Postgres cuando haga falta."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

import yaml

from aula.familia.modelo import Familia

RUTA_POR_DEFECTO = Path("datos/familia.yaml")


def cargar_familia(ruta: str | Path | None = None) -> Familia:
    ruta = Path(ruta or RUTA_POR_DEFECTO)
    if not ruta.exists():
        raise FileNotFoundError(
            f"no existe {ruta}. Crea la familia con `aula familia crear`."
        )
    with ruta.open(encoding="utf-8") as fh:
        datos = yaml.safe_load(fh) or {}
    return Familia.model_validate(datos)


def _limpiar(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {k: _limpiar(v) for k, v in valor.items() if v not in (None, [], {})}
    if isinstance(valor, list):
        return [_limpiar(v) for v in valor]
    if isinstance(valor, _dt.date):
        return valor.isoformat()
    return valor


def guardar_familia(familia: Familia, ruta: str | Path | None = None) -> Path:
    ruta = Path(ruta or RUTA_POR_DEFECTO)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            _limpiar(familia.model_dump(mode="json")),
            fh, allow_unicode=True, sort_keys=False, default_flow_style=False, width=100,
        )
    return ruta
