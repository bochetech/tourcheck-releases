"""La criba: qué se acepta del modelo y qué se descarta, con motivo."""

from __future__ import annotations

from aula.importador.codigos import IndiceCodigos
from aula.importador.extraccion import (
    criba,
    esquema_extraccion,
    extraer,
    objetivos_no_vistos,
)
from aula.importador.texto import desde_paginas
from aula.importador.trozos import trocear
from falso_llm import ModeloDeMentira, cliente_falso

TEXTO = (
    "MA05 OA 01 Representar numeros naturales de hasta mas de 6 digitos.\n"
    "MA05 OA 02 Aplicar estrategias de calculo mental para la multiplicacion.\n"
)


def preparar(texto: str = TEXTO):
    doc = desde_paginas("d", ["portada del programa", texto], titulo="Programa MA",
                        url="https://ejemplo.cl/p.pdf")
    return doc, IndiceCodigos(doc)


def test_acepta_lo_bueno_y_le_pega_la_procedencia_calculada():
    doc, indice = preparar()
    crudo = {"objetivos": [{"codigo": "MA05 OA 01", "texto": "Representar numeros."}]}
    aceptados, descartes = criba(crudo, trocear(doc, indice)[0], doc, indice)
    assert descartes == []
    assert aceptados[0].fuente.pagina == 2
    assert aceptados[0].fuente.doc == "Programa MA"
    assert aceptados[0].nivel == "05"
    assert aceptados[0].asignatura == "MA"


def test_un_codigo_inventado_con_buena_forma_se_descarta():
    """Es el caso peligroso: parece bueno y no está en el documento."""
    doc, indice = preparar()
    crudo = {"objetivos": [
        {"codigo": "MA05 OA 01", "texto": "El bueno."},
        {"codigo": "XX99 OA 99", "texto": "El inventado."},
    ]}
    aceptados, descartes = criba(crudo, trocear(doc, indice)[0], doc, indice)
    assert [o.codigo for o in aceptados] == ["MA05 OA 01"]
    assert "inventado" in descartes[0].motivo
    assert descartes[0].codigo == "XX99 OA 99"


def test_un_codigo_malformado_se_descarta_diciendo_por_que():
    doc, indice = preparar()
    crudo = {"objetivos": [{"codigo": "no-es-un-codigo", "texto": "algo"}]}
    aceptados, descartes = criba(crudo, trocear(doc, indice)[0], doc, indice)
    assert aceptados == []
    assert "forma de un código" in descartes[0].motivo


def test_un_error_en_el_tercero_no_tira_los_dos_primeros():
    doc, indice = preparar()
    crudo = {"objetivos": [
        {"codigo": "MA05 OA 01", "texto": "Uno."},
        {"codigo": "MA05 OA 02", "texto": "Dos."},
        {"codigo": "MA05 OA 03"},
    ]}
    aceptados, descartes = criba(crudo, trocear(doc, indice)[0], doc, indice)
    assert len(aceptados) == 2
    assert len(descartes) == 1


def test_normaliza_el_codigo_que_devuelve_el_modelo():
    doc, indice = preparar()
    crudo = {"objetivos": [{"codigo": "ma05 oa 1", "texto": "Representar numeros."}]}
    aceptados, _ = criba(crudo, trocear(doc, indice)[0], doc, indice)
    assert aceptados[0].codigo == "MA05 OA 01"


def test_una_lista_pelada_tambien_se_entiende():
    """Los modelos pequeños devuelven el array suelto con cierta frecuencia."""
    doc, indice = preparar()
    aceptados, _ = criba(
        [{"codigo": "MA05 OA 01", "texto": "Representar."}],
        trocear(doc, indice)[0], doc, indice,
    )
    assert len(aceptados) == 1


def test_un_trozo_perdido_no_invalida_el_documento():
    doc, indice = preparar()
    modelo = ModeloDeMentira(falla_en_trozo=1)
    trozos = trocear(doc, indice, max_caracteres=80)
    resultado = extraer(doc, trozos, cliente_falso(modelo), indice)
    assert resultado.trozos_fallidos == 1
    assert resultado.errores and "400" in resultado.errores[0]
    assert resultado.objetivos  # los demás trozos sí salieron


def test_la_cobertura_se_mide_contra_el_documento_no_contra_el_modelo():
    doc, indice = preparar()
    modelo = ModeloDeMentira()
    resultado = extraer(doc, trocear(doc, indice), cliente_falso(modelo), indice)
    assert objetivos_no_vistos(indice, resultado) == []


def test_el_esquema_no_arrastra_razonamiento_interno():
    """Todo lo que entra en el esquema viaja al modelo y le come contexto."""
    texto = str(esquema_extraccion())
    assert "peligroso" not in texto
    assert "alucin" not in texto


def test_el_esquema_no_lleva_oneOf():
    """LM Studio rechaza `oneOf` de plano. Lo aprendimos de un fallo real."""
    assert "oneOf" not in str(esquema_extraccion())
