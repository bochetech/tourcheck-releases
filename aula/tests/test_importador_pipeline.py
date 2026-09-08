"""De punta a punta: PDF real → currículo canónico → cero hallazgos bloqueantes.

Es el único test que ejerce todas las piezas juntas, y el criterio es el que
importa: que lo que salga del importador sea **utilizable**. El modelo es de
mentira pero lee de verdad el fragmento que se le manda, así que si el troceado
pierde un objetivo o la procedencia se corrompe, aquí se nota.
"""

from __future__ import annotations

import pytest

from aula.config import Config, ModeloConfig, Rol
from aula.curriculum.proponente import ProponenteConModelo
from aula.curriculum.reparador import reparar
from aula.curriculum.validator import validar
from aula.importador.catalogo import Documento
from aula.importador.descarga import adjuntar
from aula.importador.pipeline import importar
from falso_llm import PROVEEDOR, ModeloDeMentira, cliente_falso
from pdf_minimo import pdf_de_paginas

OBJETIVOS = [
    ("MA02 OA 01", "Contar numeros del 0 al 100 de 1 en 1, de 2 en 2, de 5 en 5 y de 10 en 10."),
    ("MA02 OA 02", "Leer numeros del 0 al 100 y representarlos en forma concreta y pictorica."),
    ("MA02 OA 03", "Comparar y ordenar numeros del 0 al 100 de menor a mayor y viceversa."),
    ("MA02 OA 04", "Estimar cantidades hasta 100 en situaciones concretas de la vida diaria."),
    ("MA02 OA 05", "Componer y descomponer numeros del 0 al 100 de manera aditiva."),
    ("MA02 OAA B", "Manifestar curiosidad e interes por el aprendizaje de las matematicas."),
]


def temario_pdf() -> bytes:
    paginas = [["Temario Examen Libre", "Segundo Basico", "Matematica"]]
    for i in range(0, len(OBJETIVOS), 2):
        paginas.append([f"{c} {t}" for c, t in OBJETIVOS[i : i + 2]])
    return pdf_de_paginas(paginas)


DOC = Documento(
    id="cl-temario-02-basico", tipo="pdf", clase="temario",
    titulo="Temario examen libre — 2º básico",
    url="https://www.ayudamineduc.cl/temario.pdf", nivel="02",
)


def config_falsa() -> Config:
    return Config(
        perfil="test",
        proveedores={"falso": PROVEEDOR},
        roles={
            rol: ModeloConfig(proveedor="falso", modelo="modelo-de-mentira",
                              max_tokens=4096)
            for rol in Rol
        },
    )


@pytest.fixture
def cache(tmp_path):
    destino = tmp_path / "fuentes"
    origen = tmp_path / "temario.pdf"
    origen.write_bytes(temario_pdf())
    adjuntar(DOC, origen, destino)
    return destino


def test_de_punta_a_punta_sale_un_curriculo_utilizable(cache):
    """El criterio del plan: cero bloqueantes tras el bucle de reparación."""
    modelo = ModeloDeMentira()
    curriculo, informe = importar("CL", config_falsa(), nivel="02", cache=cache,
                                  transporte=modelo)

    assert informe.cobertura == 1.0
    assert len(curriculo.objetivos) == len(OBJETIVOS)

    reparado, reparacion = reparar(
        curriculo, ProponenteConModelo(cliente_falso(modelo), permitir_agregado=False)
    )
    assert validar(reparado).bloqueantes == []


def test_todo_objetivo_lleva_su_procedencia_o_no_se_puede_auditar(cache):
    """Sin `fuente.doc` y `fuente.pagina` nadie puede comprobar nada. Regla 5."""
    curriculo, _ = importar("CL", config_falsa(), nivel="02", cache=cache,
                            transporte=ModeloDeMentira())
    for o in curriculo.objetivos:
        assert o.fuente is not None
        assert o.fuente.doc == "Temario examen libre — 2º básico"
        assert o.fuente.pagina >= 2  # la 1 es la portada
        assert o.fuente.url == DOC.url


def test_el_temario_importado_queda_declarado_como_temario(cache):
    curriculo, _ = importar("CL", config_falsa(), nivel="02", cache=cache,
                            transporte=ModeloDeMentira())
    assert sorted(curriculo.temario["02"]) == sorted(c for c, _ in OBJETIVOS)
    assert all(o.en_temario_examen for o in curriculo.objetivos)


def test_los_codigos_inventados_no_llegan_al_curriculo(cache):
    curriculo, informe = importar(
        "CL", config_falsa(), nivel="02", cache=cache,
        transporte=ModeloDeMentira(codigos_inventados=["ZZ99 OA 99", "invento"]),
    )
    assert all(o.codigo.startswith("MA02") for o in curriculo.objetivos)
    assert any("inventado" in d for d in informe.descartes)
    assert any("forma de un código" in d for d in informe.descartes)


def test_la_cobertura_se_mide_contra_el_documento_no_contra_el_modelo(cache):
    """El denominador lo calcula una expresión regular, no la IA."""
    class Perezoso(ModeloDeMentira):
        def _extraer(self, texto):
            return '{"objetivos": [], "sin_objetivos": true}'

    curriculo, informe = importar("CL", config_falsa(), nivel="02", cache=cache,
                                  transporte=Perezoso())
    assert curriculo.objetivos == []
    assert informe.codigos_en_documentos == len(OBJETIVOS)
    assert informe.cobertura == 0.0
    assert len(informe.no_vistos) == len(OBJETIVOS)


def test_con_el_modelo_caido_falla_diciendolo_y_no_deja_un_yaml_a_medias(cache):
    class Caido(ModeloDeMentira):
        def __call__(self, url, cuerpo, cabeceras, limite):
            if url.endswith("/models"):
                return {"data": [{"id": "modelo-de-mentira"}]}
            raise __import__("aula.llm.cliente", fromlist=["ErrorLLM"]).ErrorLLM(
                "no se pudo conectar con http://127.0.0.1:1234"
            )

    curriculo, informe = importar("CL", config_falsa(), nivel="02", cache=cache,
                                  transporte=Caido(), con_pases=False)
    assert curriculo.objetivos == []
    assert informe.errores
    assert "no se pudo conectar" in informe.errores[0]


def test_una_cache_vacia_dice_que_hacer(tmp_path):
    with pytest.raises(FileNotFoundError, match="fetch"):
        importar("CL", config_falsa(), nivel="02", cache=tmp_path / "vacia",
                 transporte=ModeloDeMentira())


def test_sin_pases_el_curriculo_sale_crudo_a_proposito(cache):
    """Poder mirar la extracción antes de que un modelo la toque es deliberado."""
    curriculo, informe = importar("CL", config_falsa(), nivel="02", cache=cache,
                                  transporte=ModeloDeMentira(), con_pases=False)
    assert curriculo.objetivos
    assert all(not o.items and not o.resumen for o in curriculo.objetivos)
    assert informe.informes_pases == []
