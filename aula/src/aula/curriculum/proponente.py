"""El proponente con modelo: convierte hallazgos del validador en operaciones.

Lo que hace que esto funcione con un modelo local pequeño no es el prompt, son
tres decisiones:

1. **El contexto es diminuto.** No se le manda el currículo, se le mandan los
   hallazgos. Cada uno ya trae su instrucción de reparación y sus datos
   estructurados, porque el validador se escribió para este consumidor.
2. **Decodificación restringida.** La respuesta se pide con un esquema JSON, así
   el servidor obliga al modelo a producir algo con la forma correcta. Sin esto,
   un 7-12B se inventa el formato con frecuencia.
3. **Nada se cree a ciegas.** Todo lo que vuelve se valida con Pydantic y luego
   contra el currículo real. Lo que no cuadre se descarta con un motivo, y ese
   motivo vuelve al modelo en la vuelta siguiente.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from aula.curriculum.model import Curriculum
from aula.curriculum.operaciones import Aplicacion, Operacion, OperacionSinAgregado
from aula.curriculum.validator import Hallazgo
from aula.llm.cliente import Cliente, ErrorLLM

MAX_HALLAZGOS_POR_TANDA = 25

INSTRUCCIONES = """Eres el reparador de un plan de estudios. Un validador encontró
problemas y tu tarea es proponer operaciones que los cierren.

Reglas:
- Solo puedes usar las operaciones del esquema. No inventes otras.
- Cada hallazgo trae en `reparacion` qué hay que hacer y en `datos` con qué.
- Propón como mucho una operación por hallazgo.
- Si un hallazgo no se puede cerrar con las operaciones disponibles, omítelo:
  es preferible dejarlo para que lo revise una persona que forzar un arreglo.
- No inventes códigos de objetivo que no aparezcan en los hallazgos."""


class Propuesta(BaseModel):
    operaciones: list[Operacion] = []


# El mismo vocabulario menos `agregar_objetivo`. Esa operación arrastra el modelo
# entero de un objetivo y por sí sola duplica el tamaño del esquema; con un modelo
# local pequeño conviene quitarla, y además crear objetivos de la nada es la
# operación más arriesgada. El comentario va aquí y no en un docstring porque
# Pydantic mete los docstrings en el esquema, y todo lo que entra ahí se le manda
# al modelo y le come presupuesto de contexto.
class PropuestaSinAgregado(BaseModel):
    operaciones: list[OperacionSinAgregado] = []


def esquema_de_propuesta(permitir_agregado: bool = True) -> dict[str, Any]:
    """Esquema JSON del vocabulario cerrado, para la decodificación restringida."""
    modelo = Propuesta if permitir_agregado else PropuestaSinAgregado
    esquema = modelo.model_json_schema()
    _endurecer(esquema)
    return esquema


def _endurecer(nodo: Any) -> None:
    """Adapta el esquema a lo que aceptan los motores de gramáticas locales.

    Tres ajustes, y el segundo lo aprendimos de un error real de LM Studio:

    - Los objetos se cierran (`additionalProperties: false`), que varios
      servidores exigen en modo estricto.
    - `oneOf` pasa a `anyOf`. Pydantic genera `oneOf` para uniones discriminadas
      y el motor de LM Studio lo rechaza de plano. Aquí el cambio es inocuo: las
      variantes ya son mutuamente excluyentes por el `const` del campo `op`.
    - Se quita el discriminador, que confunde a varios servidores locales.
    """
    if isinstance(nodo, dict):
        if nodo.get("type") == "object" and "additionalProperties" not in nodo:
            nodo["additionalProperties"] = False
        if "oneOf" in nodo and "anyOf" not in nodo:
            nodo["anyOf"] = nodo.pop("oneOf")
        nodo.pop("discriminator", None)
        for valor in nodo.values():
            _endurecer(valor)
    elif isinstance(nodo, list):
        for valor in nodo:
            _endurecer(valor)


def _resumir(hallazgos: list[Hallazgo]) -> list[dict]:
    """Lo mínimo que el modelo necesita: qué pasa, cómo se arregla y con qué datos."""
    return [
        {
            "regla": h.codigo_regla,
            "objetivo": h.objetivo,
            "problema": h.mensaje,
            "reparacion": h.reparacion,
            "datos": h.datos,
        }
        for h in hallazgos[:MAX_HALLAZGOS_POR_TANDA]
    ]


class ProponenteConModelo:
    """Proponente respaldado por un modelo de lenguaje."""

    def __init__(self, cliente: Cliente, tolerante: bool = True,
                 permitir_agregado: bool = True):
        self.cliente = cliente
        self.tolerante = tolerante
        self.permitir_agregado = permitir_agregado
        self.ultimo_error: str | None = None

    def __call__(
        self,
        curriculum: Curriculum,
        hallazgos: list[Hallazgo],
        rechazos: list[Aplicacion],
    ) -> list:
        self.ultimo_error = None
        contenido: dict[str, Any] = {"hallazgos": _resumir(hallazgos)}
        if rechazos:
            contenido["rechazadas_en_la_vuelta_anterior"] = [
                {"operacion": r.operacion, "motivo": r.rechazo} for r in rechazos[:10]
            ]

        mensajes = [
            {"role": "system", "content": INSTRUCCIONES},
            {"role": "user", "content": json.dumps(contenido, ensure_ascii=False)},
        ]

        try:
            respuesta = self.cliente.completar(
                mensajes,
                esquema=esquema_de_propuesta(self.permitir_agregado),
                nombre_esquema="propuesta",
            )
            crudo = respuesta.json_()
        except ErrorLLM as exc:
            self.ultimo_error = str(exc)
            if self.tolerante:
                return []  # sin modelo no hay reparación, pero tampoco se rompe nada
            raise

        return self._interpretar(crudo)

    def _interpretar(self, crudo: Any) -> list:
        """Acepta lo que valide y descarta el resto, operación por operación.

        Se interpreta una a una a propósito: que el modelo se equivoque en la
        tercera no debe tirar las dos primeras, que estaban bien.
        """
        if isinstance(crudo, list):
            crudo = {"operaciones": crudo}
        if not isinstance(crudo, dict):
            self.ultimo_error = "la respuesta no tiene la forma esperada"
            return []

        buenas = []
        descartadas = 0
        for entrada in crudo.get("operaciones") or []:
            try:
                buenas.append(Propuesta.model_validate({"operaciones": [entrada]}).operaciones[0])
            except ValidationError:
                descartadas += 1
        if descartadas:
            self.ultimo_error = f"{descartadas} operaciones mal formadas, descartadas"
        return buenas
