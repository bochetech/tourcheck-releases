"""Fusionar lo extraído y ponerle una confianza que signifique algo.

La confianza no es la opinión del modelo sobre sí mismo —esa no vale nada— sino
la suma de **señales computables**: si el código está en el documento, si dos
trozos independientes coinciden en el texto, si el largo es plausible, si el
nivel del código cuadra con el del documento.

Y la señal que más pesa es negativa: un código con la forma correcta que **no
aparece en el documento** se descarta, gane lo que gane en el resto. Es el caso
peligroso, porque tiene toda la apariencia de ser bueno. Un código malformado se
cae solo; uno bien formado e inventado se cuela.

La confianza decide qué llega a la cola de revisión del padre. Es exactamente
para lo que el modelo canónico ya tiene el campo.
"""

from __future__ import annotations

import datetime as _dt
from collections import Counter

from pydantic import BaseModel, Field

from aula.curriculum.model import (
    Curriculum,
    FuenteCurriculo,
    Licencia,
    Objetivo,
)
from aula.importador.extraccion import ObjetivoExtraido

#: Base por tener la forma de un código de objetivo.
PESO_BASE = 0.35
#: Por estar realmente en el documento. Es el que más pesa de los positivos, y
#: no tenerlo no resta: descarta.
PESO_EN_FUENTE = 0.30
#: Por que dos trozos independientes den el mismo texto.
PESO_CONFIRMADO = 0.20
#: Por un largo de texto plausible para un objetivo de aprendizaje.
PESO_LARGO_PLAUSIBLE = 0.10
#: Por que el nivel del código cuadre con el nivel del documento.
PESO_NIVEL_CUADRA = 0.05
#: Penalización cuando dos trozos dan textos distintos para el mismo código.
PENA_CONFLICTO = 0.25

LARGO_MINIMO, LARGO_MAXIMO = 30, 400


class Conflicto(BaseModel):
    """Dos trozos dieron textos distintos para el mismo código."""

    codigo: str
    variantes: list[str] = Field(default_factory=list)


class Consolidacion(BaseModel):
    objetivos: list[Objetivo] = Field(default_factory=list)
    conflictos: list[Conflicto] = Field(default_factory=list)
    descartados: dict[str, str] = Field(default_factory=dict)

    @property
    def dudosos(self) -> list[Objetivo]:
        """Los que hay que mirar a mano antes de ponérselos a un niño."""
        return [o for o in self.objetivos if o.confianza < 0.7]


def consolidar(
    extraidos: list[ObjetivoExtraido],
    *,
    codigos_en_fuente: set[str] | None = None,
    nivel_documento: str | None = None,
) -> Consolidacion:
    """Agrupa por código, elige el mejor texto y puntúa la confianza."""
    por_codigo: dict[str, list[ObjetivoExtraido]] = {}
    for e in extraidos:
        por_codigo.setdefault(e.codigo, []).append(e)

    resultado = Consolidacion()
    for codigo, apariciones in por_codigo.items():
        if codigos_en_fuente is not None and codigo not in codigos_en_fuente:
            resultado.descartados[codigo] = (
                "el código no aparece en el documento (inventado)"
            )
            continue

        textos = Counter(a.texto for a in apariciones)
        # El texto más repetido; a igualdad, el más largo, porque un objetivo
        # truncado en la frontera de un trozo siempre es el corto de los dos.
        mejor = max(textos.items(), key=lambda kv: (kv[1], len(kv[0])))[0]
        hay_conflicto = len(textos) > 1
        if hay_conflicto:
            resultado.conflictos.append(
                Conflicto(codigo=codigo, variantes=sorted(textos))
            )

        confianza = PESO_BASE
        if codigos_en_fuente is None or codigo in codigos_en_fuente:
            confianza += PESO_EN_FUENTE
        trozos_distintos = {a.trozo for a in apariciones}
        if textos[mejor] > 1 and len(trozos_distintos) > 1:
            confianza += PESO_CONFIRMADO
        if LARGO_MINIMO <= len(mejor) <= LARGO_MAXIMO:
            confianza += PESO_LARGO_PLAUSIBLE
        nivel = _primero(a.nivel for a in apariciones) or ""
        if nivel_documento and nivel == nivel_documento:
            confianza += PESO_NIVEL_CUADRA
        if hay_conflicto:
            confianza -= PENA_CONFLICTO

        principal = next(a for a in apariciones if a.texto == mejor)
        resultado.objetivos.append(
            Objetivo(
                codigo=codigo,
                texto=mejor,
                asignatura=principal.asignatura or codigo[:2],
                nivel=nivel or nivel_documento or "",
                unidad=_primero(a.unidad for a in apariciones),
                tipo=principal.tipo,
                fuente=principal.fuente,
                confianza=round(min(max(confianza, 0.0), 1.0), 2),
            )
        )

    resultado.objetivos.sort(key=lambda o: o.codigo)
    return resultado


def _primero(valores) -> str | None:
    for v in valores:
        if v:
            return v
    return None


def construir_curriculum(
    consolidacion: Consolidacion,
    *,
    id_curriculo: str,
    version: str,
    fuente: FuenteCurriculo,
    licencia: Licencia | None = None,
    es_temario: bool = False,
    vigencia_desde: _dt.date | None = None,
    plan_horas: dict[str, dict[str, float]] | None = None,
) -> Curriculum:
    """Arma el `Curriculum` canónico a partir de lo consolidado.

    Cuando el documento importado **es** el temario del examen libre, todo lo que
    salga de él va al temario con `en_temario_examen=True`. No es un atajo: el
    documento es literalmente la lista oficial de lo que se evalúa, así que la
    regla 6 pasa por construcción y no por suerte.
    """
    objetivos = []
    temario: dict[str, list[str]] = {}
    for o in consolidacion.objetivos:
        copia = o.model_copy(deep=True)
        if licencia is not None and copia.licencia is None:
            copia.licencia = licencia
        if es_temario:
            copia.en_temario_examen = True
            temario.setdefault(copia.nivel, []).append(copia.codigo)
        objetivos.append(copia)

    return Curriculum(
        id=id_curriculo,
        version=version,
        vigencia_desde=vigencia_desde or _dt.date.today(),
        fuente=fuente,
        licencia_por_defecto=licencia or Licencia(),
        objetivos=objetivos,
        temario=temario,
        plan_horas=plan_horas or {},
    )
