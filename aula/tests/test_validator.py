"""Cada regla del validador debe atrapar su fallo, y ninguna debe dar falsos positivos.

Este archivo es el criterio de verificación del plan: currículos rotos a
propósito, uno por regla.
"""

from __future__ import annotations

import pytest

from aula.curriculum import validar
from aula.curriculum.model import Fuente, Licencia
from factories import curriculo_sano, objetivo


def codigos_de_regla(resultado, regla: int) -> set[str]:
    return {h.codigo_regla for h in resultado.por_regla(regla)}


# --------------------------------------------------------------------------- sano


def test_curriculo_sano_no_genera_ningun_hallazgo():
    """Si el currículo bueno dispara alguna regla, el validador es inservible."""
    resultado = validar(curriculo_sano())
    assert resultado.hallazgos == [], [str(h) for h in resultado.hallazgos]
    assert resultado.ok


def test_todo_hallazgo_trae_instruccion_de_reparacion():
    """El consumidor del validador es el bucle de auto-reparación, no una persona."""
    c = curriculo_sano()
    c.objetivos[0].prerequisitos = ["MA02 OA 99"]
    c.objetivos[1].items = []
    c.objetivos[2].fuente = None

    resultado = validar(c)
    assert resultado.hallazgos
    for h in resultado.hallazgos:
        assert h.reparacion, f"{h.codigo_regla} no dice cómo repararse"
        assert h.datos != {} or h.regla == 12


# ------------------------------------------------------------------- reglas 1 a 12


def test_r01_detecta_ciclo_de_prerrequisitos():
    c = curriculo_sano()
    # MA02 OA 01 -> OA 02 -> OA 03 -> OA 01: ciclo cerrado.
    c.objetivos[0].prerequisitos = ["MA02 OA 03"]

    resultado = validar(c)
    assert "R01_CICLO" in codigos_de_regla(resultado, 1)
    assert not resultado.ok
    ciclo = resultado.por_regla(1)[0].datos["ciclo"]
    assert len(ciclo) >= 3


def test_r01_no_confunde_un_rombo_con_un_ciclo():
    """Dos caminos que convergen no son un ciclo; un falso positivo aquí sería grave."""
    c = curriculo_sano()
    c.objetivos.append(
        objetivo("MA02 OA 04", "Comparar numeros usando mayor y menor.",
                 prerequisitos=["MA02 OA 01"], horas=0.0)
    )
    c.objetivos[2].prerequisitos = ["MA02 OA 02", "MA02 OA 04"]

    assert validar(c).por_regla(1) == []


def test_r02_detecta_prerrequisito_inexistente():
    c = curriculo_sano()
    c.objetivos[1].prerequisitos = ["MA02 OA 99"]

    resultado = validar(c)
    assert "R02_PREREQ_INEXISTENTE" in codigos_de_regla(resultado, 2)
    assert resultado.por_regla(2)[0].datos["prerequisito_roto"] == "MA02 OA 99"
    assert not resultado.ok


def test_r03_detecta_objetivo_huerfano():
    c = curriculo_sano()
    c.objetivos[0].asignatura = ""

    resultado = validar(c)
    assert "R03_HUERFANO" in codigos_de_regla(resultado, 3)
    assert "asignatura" in resultado.por_regla(3)[0].datos["campos_faltantes"]


def test_r04_detecta_objetivo_sin_items_de_evaluacion():
    c = curriculo_sano()
    c.objetivos[2].items = []

    resultado = validar(c)
    assert "R04_SIN_ITEMS" in codigos_de_regla(resultado, 4)
    assert resultado.por_regla(4)[0].objetivo == "MA02 OA 03"


def test_r05_detecta_objetivo_sin_fuente():
    """Sin fuente no se puede distinguir un objetivo extraído de uno inventado."""
    c = curriculo_sano()
    c.objetivos[0].fuente = None

    resultado = validar(c)
    assert "R05_SIN_FUENTE" in codigos_de_regla(resultado, 5)


def test_r05_tambien_rechaza_fuente_sin_documento():
    c = curriculo_sano()
    c.objetivos[0].fuente = Fuente(doc="", pagina=1)

    assert "R05_SIN_FUENTE" in codigos_de_regla(validar(c), 5)


def test_r06_detecta_temario_no_cubierto():
    """El temario oficial es el blanco mínimo del examen libre."""
    c = curriculo_sano()
    c.temario["02"].append("MA02 OA 07")

    resultado = validar(c)
    assert "R06_TEMARIO_INCOMPLETO" in codigos_de_regla(resultado, 6)
    assert "MA02 OA 07" in resultado.por_regla(6)[0].datos["faltantes"]
    assert not resultado.ok


def test_r06_avisa_si_el_objetivo_no_esta_marcado_como_del_temario():
    c = curriculo_sano()
    c.objetivos[0].en_temario_examen = False

    resultado = validar(c)
    assert "R06_TEMARIO_SIN_MARCAR" in codigos_de_regla(resultado, 6)
    # Es advertencia: el objetivo existe, solo falta la marca.
    assert resultado.ok


def test_r07_detecta_horas_descuadradas_y_sugiere_el_factor():
    c = curriculo_sano()
    for o in c.objetivos:
        o.horas_estimadas = 5.0  # suman 15 frente a las 60 del plan oficial

    resultado = validar(c)
    assert "R07_HORAS_DESCUADRADAS" in codigos_de_regla(resultado, 7)
    assert resultado.por_regla(7)[0].datos["factor_sugerido"] == pytest.approx(4.0)


def test_r07_tolera_un_desvio_pequeno():
    c = curriculo_sano()
    c.objetivos[0].horas_estimadas = 21.0  # 61 de 60: dentro del 10%

    assert validar(c).por_regla(7) == []


def test_r08_detecta_codigos_duplicados():
    c = curriculo_sano()
    c.objetivos.append(objetivo("MA02 OA 01", "Contar numeros hasta el cien.", horas=0.0))

    resultado = validar(c)
    assert "R08_DUPLICADO" in codigos_de_regla(resultado, 8)
    assert resultado.por_regla(8)[0].datos["repeticiones"] == 2
    assert not resultado.ok


def test_r09_detecta_cadena_de_prerrequisitos_absurda():
    """Una cadena larguísima casi siempre es mala extracción, no profundidad real."""
    c = curriculo_sano()
    anterior = "MA02 OA 03"
    for i in range(4, 40):
        codigo = f"MA02 OA {i:02d}"
        c.objetivos.append(
            objetivo(codigo, "Practicar el conteo con apoyo.",
                     prerequisitos=[anterior], horas=0.0)
        )
        anterior = codigo

    resultado = validar(c)
    assert "R09_CADENA_LARGA" in codigos_de_regla(resultado, 9)
    # Es advertencia: sospechoso, pero no impide usar el plan.
    assert resultado.ok


def test_r10_detecta_licencia_desconocida():
    """La licencia decide qué se puede redistribuir si esto sirve a otras familias."""
    c = curriculo_sano()
    c.objetivos[0].licencia = Licencia()

    resultado = validar(c)
    assert "R10_SIN_LICENCIA" in codigos_de_regla(resultado, 10)


def test_r11_detecta_texto_demasiado_dificil_para_el_nivel():
    c = curriculo_sano()
    c.objetivos[0].texto = (
        "Conceptualizar representaciones numericas polivalentes mediante "
        "procedimientos algoritmicos progresivamente sistematizados que "
        "posibiliten la transferencia interdisciplinaria correspondiente."
    )

    resultado = validar(c)
    assert "R11_POCO_LEGIBLE" in codigos_de_regla(resultado, 11)
    assert resultado.por_regla(11)[0].datos["indice"] < 70


def test_r12_exige_version():
    c = curriculo_sano()
    c.version = "  "

    resultado = validar(c)
    assert "R12_SIN_VERSION" in codigos_de_regla(resultado, 12)
    assert not resultado.ok


def test_r12_avisa_si_falta_la_vigencia():
    c = curriculo_sano()
    c.vigencia_desde = None

    resultado = validar(c)
    assert "R12_SIN_VIGENCIA" in codigos_de_regla(resultado, 12)
    assert resultado.ok  # solo advertencia


# ----------------------------------------------------------------- validador global


def test_el_validador_reporta_todos_los_fallos_de_una_vez():
    """El bucle de auto-reparación necesita la lista completa, no el primer error."""
    c = curriculo_sano()
    c.objetivos[0].items = []
    c.objetivos[1].fuente = None
    c.objetivos[2].prerequisitos = ["NO EXISTE"]

    reglas = {h.regla for h in validar(c).hallazgos}
    assert {2, 4, 5} <= reglas
