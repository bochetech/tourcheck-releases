"""Trocear sin perder objetivos. El troceo ingenuo pierde justo lo que buscamos."""

from __future__ import annotations

from aula.importador.codigos import IndiceCodigos
from aula.importador.texto import desde_paginas
from aula.importador.trozos import trocear


def documento(n: int, por_pagina: int = 4):
    """Un documento sintético con `n` objetivos numerados y texto de relleno."""
    paginas, linea = [], []
    for i in range(1, n + 1):
        linea.append(
            f"MA05 OA {i:02d} Objetivo numero {i} con suficiente texto de relleno "
            f"como para que ocupe un espacio realista en el documento."
        )
        if len(linea) == por_pagina:
            paginas.append("\n".join(linea))
            linea = []
    if linea:
        paginas.append("\n".join(linea))
    return desde_paginas("d", paginas, titulo="Doc")


def test_ningun_objetivo_se_pierde_al_trocear():
    """La propiedad que justifica cortar en fronteras de código y no cada N letras."""
    doc = documento(30)
    indice = IndiceCodigos(doc)
    trozos = trocear(doc, indice, max_caracteres=400)
    vistos = {c for t in trozos for c in t.codigos}
    assert vistos == set(indice.codigos)
    assert len(trozos) > 1  # que de verdad se haya troceado


def test_ningun_objetivo_queda_partido_por_la_mitad():
    """Cada código aparece completo, con su texto, en algún trozo."""
    doc = documento(20)
    trozos = trocear(doc, max_caracteres=400)
    for codigo in IndiceCodigos(doc).codigos:
        assert any(codigo in t.texto for t in trozos)


def test_el_solape_repite_el_ultimo_bloque_a_proposito():
    """Los duplicados son señal de confianza: dos trozos que coinciden puntúan más."""
    doc = documento(20)
    con_solape = trocear(doc, max_caracteres=400, solape=1)
    sin_solape = trocear(doc, max_caracteres=400, solape=0)
    apariciones = [c for t in con_solape for c in t.codigos]
    assert len(apariciones) > len(set(apariciones))
    assert len([c for t in sin_solape for c in t.codigos]) == len(set(apariciones))


def test_los_trozos_saben_de_que_paginas_vienen():
    doc = documento(12, por_pagina=3)
    trozos = trocear(doc, max_caracteres=100_000)
    assert trozos[0].pagina_desde == 1
    assert trozos[-1].pagina_hasta == len(doc.paginas)


def test_un_documento_sin_codigos_cae_en_troceo_por_parrafos():
    """Un plan de horas o una portada no tienen códigos y aun así hay que leerlos."""
    doc = desde_paginas("d", ["\n\n".join(f"Parrafo numero {i} " * 30 for i in range(20))])
    trozos = trocear(doc, max_caracteres=1000)
    assert len(trozos) > 1
    assert all(t.codigos == [] for t in trozos)


def test_el_texto_anterior_al_primer_codigo_no_se_tira():
    """Descartarlo por suposición es el atajo típico que pierde contenido."""
    preambulo = "Presentacion del programa. " * 20
    doc = desde_paginas("d", [preambulo + "\nMA05 OA 01 contar numeros hasta el cien."])
    trozos = trocear(doc, max_caracteres=10_000)
    assert any("Presentacion del programa" in t.texto for t in trozos)


def test_los_trozos_cubren_el_documento_sin_huecos():
    doc = documento(15)
    trozos = trocear(doc, max_caracteres=500, solape=0)
    assert trozos[0].inicio <= 0 or trozos[0].inicio == 0
    for anterior, siguiente in zip(trozos, trozos[1:]):
        assert siguiente.inicio == anterior.fin
    assert trozos[-1].fin == len(doc.texto)
