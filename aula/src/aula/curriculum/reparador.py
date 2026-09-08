"""El bucle de auto-reparación: el validador como retroalimentación de la IA.

Esta es la pieza que hace que el plan se cree solo. El validador no es una puerta
para el padre: es el criterio contra el que el importador se corrige a sí mismo,
vuelta tras vuelta, hasta que solo queda lo que la máquina no supo cerrar.

Dos propiedades de seguridad, y la segunda es la que importa:

1. El modelo solo puede proponer operaciones del vocabulario cerrado de
   `operaciones.py`; el código valida cada una antes de aplicarla.
2. **Una vuelta que empeore el plan se descarta entera.** Se trabaja sobre una
   copia y solo se adopta si los hallazgos bloqueantes bajaron. Un bucle que
   puede degradar el currículo es peor que no tener bucle.
"""

from __future__ import annotations

from typing import Callable, Protocol

from pydantic import BaseModel, Field

from aula.curriculum.model import Curriculum
from aula.curriculum.operaciones import Aplicacion, aplicar
from aula.curriculum.validator import Hallazgo, Resultado, validar

MAX_VUELTAS = 4


class Proponente(Protocol):
    """Quien propone arreglos: en producción un LLM, en los tests un guion."""

    def __call__(
        self,
        curriculum: Curriculum,
        hallazgos: list[Hallazgo],
        rechazos: list[Aplicacion],
    ) -> list: ...


class Vuelta(BaseModel):
    """Una iteración del bucle, con lo que se intentó y lo que se consiguió."""

    numero: int
    bloqueantes_antes: int
    bloqueantes_despues: int
    total_antes: int
    total_despues: int
    aplicaciones: list[Aplicacion] = Field(default_factory=list)
    adoptada: bool = True
    motivo: str = ""


class Reparacion(BaseModel):
    """Resultado del bucle completo."""

    vueltas: list[Vuelta] = Field(default_factory=list)
    hallazgos_finales: list[Hallazgo] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """El plan quedó utilizable: sin bloqueantes."""
        return not [h for h in self.hallazgos_finales if h.severidad.value == "bloqueante"]

    @property
    def pendientes_para_el_padre(self) -> list[Hallazgo]:
        """Lo único que debería llegar a la cola de excepciones."""
        return self.hallazgos_finales

    def resumen(self) -> str:
        arreglados = (
            self.vueltas[0].total_antes - self.vueltas[-1].total_despues
            if self.vueltas
            else 0
        )
        return (
            f"{len(self.vueltas)} vueltas, {arreglados} hallazgos cerrados solos, "
            f"{len(self.hallazgos_finales)} para revisar"
        )


def _cuenta(resultado: Resultado) -> tuple[int, int]:
    return len(resultado.bloqueantes), len(resultado.hallazgos)


def reparar(
    curriculum: Curriculum,
    proponer: Proponente,
    max_vueltas: int = MAX_VUELTAS,
    al_avanzar: Callable[[Vuelta], None] | None = None,
) -> tuple[Curriculum, Reparacion]:
    """Corre el bucle hasta dejar el plan sin bloqueantes o agotar los intentos.

    Devuelve el currículo reparado (una copia; el original no se toca) y la
    bitácora de lo que pasó en cada vuelta.
    """
    actual = curriculum.model_copy(deep=True)
    reparacion = Reparacion()
    rechazos: list[Aplicacion] = []

    for numero in range(1, max_vueltas + 1):
        resultado = validar(actual)
        if resultado.ok and not resultado.hallazgos:
            break

        propuestas = proponer(actual, resultado.hallazgos, rechazos)
        if not propuestas:
            break  # el proponente se rindió: lo que queda es para el padre

        candidato = actual.model_copy(deep=True)
        aplicaciones = aplicar(candidato, propuestas)
        despues = validar(candidato)

        bloq_antes, total_antes = _cuenta(resultado)
        bloq_despues, total_despues = _cuenta(despues)

        mejora = (bloq_despues, total_despues) < (bloq_antes, total_antes)
        vuelta = Vuelta(
            numero=numero,
            bloqueantes_antes=bloq_antes,
            bloqueantes_despues=bloq_despues,
            total_antes=total_antes,
            total_despues=total_despues,
            aplicaciones=aplicaciones,
            adoptada=mejora,
            motivo="" if mejora else "la vuelta no mejoró el plan: se descarta entera",
        )
        reparacion.vueltas.append(vuelta)
        if al_avanzar is not None:
            al_avanzar(vuelta)

        if not mejora:
            break

        actual = candidato
        rechazos = [a for a in aplicaciones if not a.aplicada]

    reparacion.hallazgos_finales = validar(actual).hallazgos
    return actual, reparacion
