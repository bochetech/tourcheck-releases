"""El índice de códigos: la parte del importador que no depende de ninguna IA."""

from __future__ import annotations

from aula.curriculum.model import TipoObjetivo
from aula.importador.codigos import IndiceCodigos, indexar_codigos, normalizar
from aula.importador.texto import desde_paginas


def doc(*paginas: str):
    return desde_paginas("d", list(paginas), titulo="Doc", url="https://ejemplo.cl/d")


def test_reconoce_las_dos_formas_reales_del_curriculo_chileno():
    """`MA05 OA 01` y `MA05 OAA B`, verificadas contra documentos del MINEDUC."""
    encontrados = indexar_codigos(doc("MA05 OA 01 contar. MA05 OAA B respetar."))
    assert [c.codigo for c in encontrados] == ["MA05 OA 01", "MA05 OAA B"]
    assert encontrados[0].tipo is TipoObjetivo.CONOCIMIENTO
    assert encontrados[1].tipo is TipoObjetivo.ACTITUD


def test_normaliza_para_que_dos_escrituras_no_parezcan_dos_objetivos():
    """Sin normalizar, `ma05 oa 1` y `MA05 OA 01` se contarían como duplicados."""
    assert normalizar("ma05  oa  1") == "MA05 OA 01"
    assert normalizar("MA05 OAA b") == "MA05 OAA B"


def test_lo_que_no_es_un_codigo_no_lo_es():
    assert normalizar("no-es-un-codigo") is None
    assert normalizar("") is None
    assert normalizar("Matematica 5 basico") is None


def test_el_salto_de_linea_del_pdf_no_rompe_el_codigo():
    """Al pasar un PDF a texto, el espacio del código puede volverse un salto."""
    assert [c.codigo for c in indexar_codigos(doc("MA05\nOA\n01 contar"))] == ["MA05 OA 01"]


def test_la_procedencia_sale_del_documento_no_del_modelo():
    indice = IndiceCodigos(doc("portada", "MA05 OA 01 contar", "MA05 OA 02 sumar"))
    assert indice.fuente_de("MA05 OA 02").pagina == 3
    assert indice.fuente_de("MA05 OA 02").doc == "Doc"
    assert indice.fuente_de("MA05 OA 02").url == "https://ejemplo.cl/d"


def test_un_codigo_que_no_esta_no_tiene_procedencia():
    """Es la comprobación que atrapa una alucinación bien formada."""
    indice = IndiceCodigos(doc("MA05 OA 01 contar"))
    assert indice.fuente_de("MA05 OA 99") is None
    assert "MA05 OA 99" not in indice


def test_cuenta_codigos_distintos_no_apariciones():
    indice = IndiceCodigos(doc("MA05 OA 01 contar", "MA05 OA 01 otra vez"))
    assert len(indice) == 1
    assert len(indice.apariciones) == 2
    assert indice.fuente_de("MA05 OA 01").pagina == 1  # la primera aparición


def test_conoce_los_niveles_y_asignaturas_que_contiene():
    indice = IndiceCodigos(doc("MA05 OA 01 x", "LE02 OA 03 y"))
    assert indice.niveles() == {"05", "02"}
    assert indice.asignaturas() == {"MA", "LE"}
