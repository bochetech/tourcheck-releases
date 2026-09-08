"""Asignatura y nivel de un documento. Equivocarse aquí etiqueta mal 206 páginas."""

from __future__ import annotations

import pytest

from aula.importador.contexto import detectar, detectar_asignatura, detectar_nivel


@pytest.mark.parametrize(
    "portada,esperado",
    [
        ("Programa de Estudio\nMatematica\nQuinto Basico", "05"),
        ("PROGRAMA DE ESTUDIO Lenguaje y Comunicación 2º básico", "02"),
        ("Historia, Geografía y Ciencias Sociales — Séptimo Año Básico", "07"),
        ("Matemática · III medio", "3M"),
        ("Ciencias Naturales 1º medio", "1M"),
        ("Un documento sin nivel declarado", None),
    ],
)
def test_detecta_el_nivel_en_las_formas_que_usa_el_mineduc(portada, esperado):
    assert detectar_nivel(portada) == esperado


@pytest.mark.parametrize(
    "portada,esperado",
    [
        ("Programa de Estudio Matematica", "MA"),
        ("Lengua y Literatura", "LE"),
        ("Educación Física y Salud", "EF"),
        ("Historia, Geografía y Ciencias Sociales", "HI"),
        ("Un documento de nada en particular", None),
    ],
)
def test_detecta_la_asignatura_por_la_portada(portada, esperado):
    assert detectar_asignatura(portada) == esperado


def test_lo_declarado_manda_sobre_lo_detectado():
    """El catálogo es la afirmación de una persona; la portada, una conjetura."""
    ctx = detectar("Matematica Quinto Basico", nivel="02")
    assert ctx.nivel == "02"
    assert ctx.origen_nivel == "declarado"
    assert ctx.origen_asignatura == "detectada en la portada"


def test_solo_se_mira_el_principio_del_documento():
    """Más adelante un programa cita otros niveles y ensuciaría la detección."""
    texto = "Matematica Quinto Basico " + ("x " * 10_000) + " Segundo Basico"
    assert detectar_nivel(texto) == "05"


def test_un_contexto_incompleto_se_sabe_incompleto():
    assert not detectar("Matematica sin nivel").completo
    assert detectar("Matematica Quinto Basico").completo
