"""Modelo canónico de un plan de estudios, independiente del país.

Un `Curriculum` es un grafo de `Objetivo`s atómicos. En Chile cada objetivo es un
OA de las Bases Curriculares (`MA05 OA 01`); en otro país será otra cosa. El motor
de tutoría solo conoce este modelo, nunca la fuente concreta.
"""

from __future__ import annotations

import datetime as _dt
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class TipoObjetivo(str, Enum):
    """Los tres tipos de objetivo que distinguen las Bases Curriculares."""

    CONOCIMIENTO = "conocimiento"
    HABILIDAD = "habilidad"
    ACTITUD = "actitud"  # los OAA chilenos


class Prioridad(str, Enum):
    """Priorización Curricular del MINEDUC: qué es imprescindible y qué complementa."""

    NIVEL_1 = "nivel-1"  # imprescindible
    NIVEL_2 = "nivel-2"  # complementario


class Licencia(BaseModel):
    """Licencia de un recurso concreto.

    `curriculumnacional.cl` no tiene una licencia única: conviven CC BY-SA y
    "todos los derechos reservados" según el recurso. Por eso la licencia viaja
    pegada al objetivo y no al currículo entero.
    """

    tipo: str = "desconocida"
    url: str | None = None
    puede_redistribuir: bool = False


class Fuente(BaseModel):
    """De dónde salió el objetivo. Sin esto no se puede auditar ni corregir."""

    doc: str
    pagina: int | None = None
    url: str | None = None


class Objetivo(BaseModel):
    """Un objetivo de aprendizaje atómico: la unidad de dominio del sistema."""

    codigo: str
    texto: str
    asignatura: str
    nivel: str
    unidad: str | None = None
    tipo: TipoObjetivo = TipoObjetivo.CONOCIMIENTO
    prioridad: Prioridad | None = None

    en_temario_examen: bool = False
    prerequisitos: list[str] = Field(default_factory=list)
    horas_estimadas: float = 0.0

    # Resumen denso para el índice RAG. Se indexa esto y no el PDF crudo: es lo
    # que mantiene el contexto recuperado por debajo del presupuesto de tokens.
    resumen: str | None = None

    items: list[str] = Field(default_factory=list)
    fuente: Fuente | None = None
    licencia: Licencia | None = None

    # 0..1 — cuán limpia fue la extracción. Decide qué llega a la cola de
    # excepciones del padre y qué se usa directamente.
    confianza: float = 1.0

    @field_validator("codigo")
    @classmethod
    def _codigo_no_vacio(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("el código del objetivo no puede estar vacío")
        return v.strip()

    @field_validator("confianza")
    @classmethod
    def _confianza_en_rango(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confianza debe estar entre 0 y 1, no {v}")
        return v


class FuenteCurriculo(BaseModel):
    """Origen institucional del currículo completo."""

    pais: str
    organismo: str
    url: str | None = None


class Curriculum(BaseModel):
    """Un plan de estudios versionado y fijable por estudiante.

    El versionado no es burocracia: el currículo chileno está en disputa (el CNED
    rechazó dos veces la actualización de las Bases) y la estructura 8+4 pasa a
    6+6 en 2027. Un niño no debe cambiar de currículo a mitad de año porque el
    ministerio publicó algo nuevo.
    """

    id: str
    version: str
    vigencia_desde: _dt.date | None = None
    vigencia_hasta: _dt.date | None = None

    fuente: FuenteCurriculo
    licencia_por_defecto: Licencia = Field(default_factory=Licencia)

    objetivos: list[Objetivo] = Field(default_factory=list)

    # nivel -> códigos que el temario oficial del examen libre declara.
    temario: dict[str, list[str]] = Field(default_factory=dict)

    # nivel -> asignatura -> horas anuales del plan de estudio oficial.
    plan_horas: dict[str, dict[str, float]] = Field(default_factory=dict)

    semanas_lectivas: int = 38

    # ---- Índices de conveniencia -------------------------------------------------

    def por_codigo(self) -> dict[str, Objetivo]:
        """Índice código -> objetivo. Los duplicados los detecta la regla 8."""
        return {o.codigo: o for o in self.objetivos}

    def niveles(self) -> set[str]:
        return {o.nivel for o in self.objetivos}

    def objetivos_de(self, nivel: str, asignatura: str | None = None) -> list[Objetivo]:
        return [
            o
            for o in self.objetivos
            if o.nivel == nivel and (asignatura is None or o.asignatura == asignatura)
        ]
