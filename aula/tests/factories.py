"""Constructores de currículos de prueba.

`curriculo_sano()` debe pasar las 12 reglas sin un solo hallazgo. Cada test lo
rompe de una forma concreta y comprueba que la regla correspondiente lo atrapa.
"""

from __future__ import annotations

import datetime as dt

from aula.curriculum.model import (
    Curriculum,
    Fuente,
    FuenteCurriculo,
    Licencia,
    Objetivo,
    Prioridad,
    TipoObjetivo,
)

LICENCIA_ABIERTA = Licencia(
    tipo="CC-BY-SA",
    url="https://creativecommons.org/licenses/by-sa/4.0/",
    puede_redistribuir=True,
)


def objetivo(
    codigo: str,
    texto: str,
    *,
    prerequisitos: list[str] | None = None,
    horas: float = 10.0,
    nivel: str = "02",
    asignatura: str = "MA",
    items: list[str] | None = None,
) -> Objetivo:
    return Objetivo(
        codigo=codigo,
        texto=texto,
        asignatura=asignatura,
        nivel=nivel,
        unidad="Unidad 1",
        tipo=TipoObjetivo.CONOCIMIENTO,
        prioridad=Prioridad.NIVEL_1,
        en_temario_examen=True,
        prerequisitos=prerequisitos or [],
        horas_estimadas=horas,
        resumen=f"Resumen de {codigo}.",
        items=items if items is not None else [f"{codigo}-item-1"],
        fuente=Fuente(doc="Temario 2 basico", pagina=3, url="https://ejemplo.cl/t.pdf"),
        licencia=LICENCIA_ABIERTA,
        confianza=0.95,
    )


def curriculo_sano() -> Curriculum:
    """Un currículo mínimo pero completo que no debe generar ningún hallazgo."""
    objetivos = [
        objetivo("MA02 OA 01", "Contar y leer numeros hasta el cien.", horas=20.0),
        objetivo(
            "MA02 OA 02",
            "Sumar numeros de dos cifras con material concreto.",
            prerequisitos=["MA02 OA 01"],
            horas=20.0,
        ),
        objetivo(
            "MA02 OA 03",
            "Restar numeros de dos cifras y revisar el resultado.",
            prerequisitos=["MA02 OA 02"],
            horas=20.0,
        ),
    ]
    return Curriculum(
        id="cl-mineduc-test",
        version="2026-03",
        vigencia_desde=dt.date(2026, 3, 4),
        fuente=FuenteCurriculo(
            pais="CL", organismo="MINEDUC-UCE", url="https://www.curriculumnacional.cl/"
        ),
        licencia_por_defecto=LICENCIA_ABIERTA,
        objetivos=objetivos,
        temario={"02": ["MA02 OA 01", "MA02 OA 02", "MA02 OA 03"]},
        plan_horas={"02": {"MA": 60.0}},
        semanas_lectivas=38,
    )
