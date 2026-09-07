"""El contador de sílabas y el índice de legibilidad sostienen la regla 11."""

import pytest

from aula.curriculum.validator import contar_silabas, fernandez_huerta


@pytest.mark.parametrize(
    "palabra, esperado",
    [
        ("casa", 2),
        ("numero", 3),
        ("aereo", 4),      # a-e-re-o: dos vocales fuertes seguidas hacen hiato
        ("cuento", 2),     # ue es diptongo
        ("día", 2),        # la tilde en la débil rompe el diptongo: dí-a
        ("dia", 1),        # sin tilde es diptongo: una sola sílaba
        ("murcielago", 4),
        ("sol", 1),
        ("", 0),
    ],
)
def test_contar_silabas(palabra, esperado):
    assert contar_silabas(palabra) == esperado


def test_texto_simple_puntua_mas_alto_que_texto_complejo():
    simple = "El gato come pan. La nina lee un libro. El sol brilla hoy."
    complejo = (
        "La conceptualizacion epistemologica de las representaciones simbolicas "
        "requiere una sistematizacion metodologica interdisciplinaria."
    )
    assert fernandez_huerta(simple) > fernandez_huerta(complejo)


def test_devuelve_none_si_no_hay_texto_suficiente():
    assert fernandez_huerta("Contar.") is None
