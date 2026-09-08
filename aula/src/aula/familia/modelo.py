"""Quién usa el sistema y con qué plan de estudios.

Multi-estudiante desde el primer día, aunque la primera familia tenga dos hijos:
añadirlo después obliga a reescribir el esquema entero, y hacerlo ahora cuesta
casi nada.

La decisión que más consecuencias tiene está en `Asignacion`: **el currículo se
fija por versión**. Si el ministerio publica una versión nueva a mitad de año, el
niño sigue con la que empezó hasta que un adulto decida migrarlo, y la migración
queda registrada. No es burocracia: el currículo chileno está en disputa (el CNED
rechazó dos veces la actualización de las Bases) y la estructura 8+4 pasa a 6+6
en 2027. Un plan que cambia solo bajo los pies de un niño es un plan roto.
"""

from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from enum import Enum

from pydantic import BaseModel, Field, field_validator

#: Por debajo de esta edad el perfil por defecto es Explorador.
EDAD_LIMITE_EXPLORADOR = 10


class ModoUI(str, Enum):
    """Las dos pieles. No es un tamaño de letra: son dos productos."""

    EXPLORADOR = "explorador"  # táctil, audio primero, compañero visible
    TALLER = "taller"          # denso, datos, nada infantilizado


class PerfilVoz(str, Enum):
    """Cómo se captura la voz, que depende de la edad mucho más que del gusto."""

    RESTRINGIDA = "restringida"  # pulsar para hablar + vocabulario esperado
    ABIERTA = "abierta"          # conversación libre


def _identificador(nombre: str) -> str:
    """Convierte un nombre en un id estable, legible y sin acentos."""
    plano = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    limpio = re.sub(r"[^a-zA-Z0-9]+", "-", plano).strip("-").lower()
    return limpio or "sin-nombre"


class Adulto(BaseModel):
    """Quien acompaña. Ve el panel, pone los topes y revisa las transcripciones."""

    id: str = ""
    nombre: str
    correo: str | None = None

    def model_post_init(self, _contexto) -> None:
        if not self.id:
            self.id = _identificador(self.nombre)


class Asignacion(BaseModel):
    """El plan que le toca a un estudiante, fijado a una versión concreta."""

    curriculum_id: str
    version: str
    nivel: str
    desde: _dt.date = Field(default_factory=_dt.date.today)
    nota: str = ""


class Estudiante(BaseModel):
    """Un niño, con su plan fijado, su piel y sus límites."""

    id: str = ""
    nombre: str
    nacimiento: _dt.date

    modo_ui: ModoUI | None = None
    perfil_voz: PerfilVoz | None = None
    nombre_companero: str = "Copi"

    asignacion: Asignacion | None = None
    historial: list[Asignacion] = Field(default_factory=list)

    minutos_diarios: int = 120
    presupuesto_mensual_usd: float = 4.0

    def model_post_init(self, _contexto) -> None:
        if not self.id:
            self.id = _identificador(self.nombre)

    @field_validator("presupuesto_mensual_usd")
    @classmethod
    def _presupuesto_no_negativo(cls, v: float) -> float:
        if v < 0:
            raise ValueError("el presupuesto no puede ser negativo")
        return v

    # -- derivados -------------------------------------------------------------

    def edad(self, hoy: _dt.date | None = None) -> int:
        hoy = hoy or _dt.date.today()
        años = hoy.year - self.nacimiento.year
        if (hoy.month, hoy.day) < (self.nacimiento.month, self.nacimiento.day):
            años -= 1
        return años

    def modo_efectivo(self, hoy: _dt.date | None = None) -> ModoUI:
        """La piel que le toca. La edad decide por defecto; el adulto puede fijarla.

        Se puede fijar a mano a propósito: un niño de 11 con dificultades de
        lectura puede necesitar Explorador, y uno de 9 muy adelantado, Taller.
        """
        if self.modo_ui is not None:
            return self.modo_ui
        return (
            ModoUI.EXPLORADOR
            if self.edad(hoy) < EDAD_LIMITE_EXPLORADOR
            else ModoUI.TALLER
        )

    def voz_efectiva(self, hoy: _dt.date | None = None) -> PerfilVoz:
        """Con voces infantiles el reconocimiento falla mucho: por eso va por edad."""
        if self.perfil_voz is not None:
            return self.perfil_voz
        return (
            PerfilVoz.RESTRINGIDA
            if self.modo_efectivo(hoy) is ModoUI.EXPLORADOR
            else PerfilVoz.ABIERTA
        )

    # -- asignación ------------------------------------------------------------

    def asignar(self, asignacion: Asignacion) -> None:
        """Le asigna un plan, guardando el anterior en el historial."""
        if self.asignacion is not None:
            if (
                self.asignacion.curriculum_id == asignacion.curriculum_id
                and self.asignacion.version == asignacion.version
                and self.asignacion.nivel == asignacion.nivel
            ):
                raise ValueError(f"{self.nombre} ya tiene asignado ese plan")
            self.historial.append(self.asignacion)
        self.asignacion = asignacion


class Familia(BaseModel):
    """Una instalación: los adultos que acompañan y los niños que aprenden."""

    id: str = ""
    nombre: str
    pais: str = "CL"
    adultos: list[Adulto] = Field(default_factory=list)
    estudiantes: list[Estudiante] = Field(default_factory=list)

    def model_post_init(self, _contexto) -> None:
        if not self.id:
            self.id = _identificador(self.nombre)

    def estudiante(self, id_o_nombre: str) -> Estudiante:
        clave = _identificador(id_o_nombre)
        for e in self.estudiantes:
            if e.id == clave:
                return e
        conocidos = ", ".join(e.id for e in self.estudiantes) or "ninguno"
        raise KeyError(f"no hay ningún estudiante '{id_o_nombre}'. Hay: {conocidos}")

    def agregar_estudiante(self, estudiante: Estudiante) -> Estudiante:
        if any(e.id == estudiante.id for e in self.estudiantes):
            raise ValueError(f"ya hay un estudiante con el id '{estudiante.id}'")
        self.estudiantes.append(estudiante)
        return estudiante

    def agregar_adulto(self, adulto: Adulto) -> Adulto:
        if any(a.id == adulto.id for a in self.adultos):
            raise ValueError(f"ya hay un adulto con el id '{adulto.id}'")
        self.adultos.append(adulto)
        return adulto

    @property
    def presupuesto_total_usd(self) -> float:
        return round(sum(e.presupuesto_mensual_usd for e in self.estudiantes), 2)
