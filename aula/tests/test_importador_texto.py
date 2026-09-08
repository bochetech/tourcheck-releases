"""Texto y procedencia: la propiedad que hace auditable todo el importador.

Los tests van contra un PDF **de verdad**, generado en el propio test. Un texto
simulado no puede demostrar que el número de página sobrevive del documento a
`Fuente.pagina`, que es justo lo que hay que demostrar.
"""

from __future__ import annotations

import pytest

from aula.importador.texto import (
    MIN_CARACTERES_POR_PAGINA,
    SinCapaDeTexto,
    desde_paginas,
    leer_texto,
    texto_de_html,
    texto_de_pdf,
)
from pdf_minimo import pdf_de_paginas

PAGINAS = [
    ["Programa de Estudio Matematica", "Unidad 1: numeros"],
    ["MA05 OA 01 Representar numeros naturales de hasta mas de 6 digitos."],
    ["MA05 OA 02 Aplicar estrategias de calculo mental para la multiplicacion."],
]


@pytest.fixture
def pdf(tmp_path):
    ruta = tmp_path / "programa.pdf"
    ruta.write_bytes(pdf_de_paginas(PAGINAS))
    return ruta


def test_lee_todas_las_paginas_del_pdf(pdf):
    doc = texto_de_pdf(pdf)
    assert len(doc.paginas) == 3
    assert "Representar numeros naturales" in doc.texto


def test_el_numero_de_pagina_sobrevive_hasta_la_procedencia(pdf):
    """Sin esto nadie puede comprobar si un objetivo se extrajo o se inventó."""
    doc = texto_de_pdf(pdf, titulo="Programa MA", url="https://ejemplo.cl/p.pdf")
    posicion = doc.texto.index("Aplicar estrategias")
    fuente = doc.procedencia_en(posicion)
    assert fuente.pagina == 3
    assert fuente.doc == "Programa MA"
    assert fuente.url == "https://ejemplo.cl/p.pdf"


def test_la_procedencia_es_correcta_en_la_frontera_entre_paginas():
    """El primer carácter de una página es de esa página, no de la anterior."""
    doc = desde_paginas("x", ["primera pagina", "segunda pagina"])
    inicio_segunda = doc.paginas[1].offset
    assert doc.pagina_en(inicio_segunda - 1) == 1
    assert doc.pagina_en(inicio_segunda) == 2


def test_un_pdf_escaneado_se_denuncia_en_vez_de_devolver_nada(tmp_path):
    """Un currículo vacío en silencio es peor que un error."""
    ruta = tmp_path / "escaneado.pdf"
    ruta.write_bytes(pdf_de_paginas([[""], [""], [""]]))
    with pytest.raises(SinCapaDeTexto, match="escaneado"):
        texto_de_pdf(ruta)


def test_el_umbral_de_escaneo_deja_pasar_un_documento_con_poco_texto(tmp_path):
    ruta = tmp_path / "corto.pdf"
    largo = "x" * (MIN_CARACTERES_POR_PAGINA + 20)
    ruta.write_bytes(pdf_de_paginas([[largo]]))
    assert texto_de_pdf(ruta).texto.strip()


def test_html_a_texto_sin_dependencias(tmp_path):
    ruta = tmp_path / "oa.html"
    ruta.write_text(
        "<html><head><style>p{color:red}</style></head><body>"
        "<script>var x = 'no debe salir';</script>"
        "<p>MA05 OA 01 Representar n&uacute;meros</p><p>Otra cosa</p>"
        "</body></html>",
        encoding="utf-8",
    )
    doc = texto_de_html(ruta, url="https://ejemplo.cl/oa")
    assert "MA05 OA 01 Representar números" in doc.texto
    assert "no debe salir" not in doc.texto
    assert "color:red" not in doc.texto


def test_leer_texto_elige_el_lector_por_la_extension(pdf, tmp_path):
    assert len(leer_texto(pdf).paginas) == 3
    txt = tmp_path / "suelto.txt"
    txt.write_text("MA05 OA 01 algo", encoding="utf-8")
    assert leer_texto(txt).texto == "MA05 OA 01 algo"


def test_se_colapsan_los_espacios_pero_no_los_saltos_de_linea():
    """Los saltos importan: cada OA empieza en línea propia y eso guía el índice."""
    doc = desde_paginas("x", ["hola    mundo\nMA05  OA  01\n\n\n\notra cosa"])
    assert doc.texto == "hola mundo\nMA05 OA 01\n\notra cosa"
