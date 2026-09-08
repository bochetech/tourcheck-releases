"""La caché: portátil, verificable y sin tocar la red en ningún test."""

from __future__ import annotations

import pytest

from aula.importador.catalogo import Documento, documentos, por_id
from aula.importador.descarga import (
    ErrorDescarga,
    adjuntar,
    cargar_manifiesto,
    descargar,
    traer_todos,
    verificar,
)

DOC = Documento(
    id="cl-temario-02-basico", tipo="pdf", clase="temario",
    titulo="Temario 2º básico", url="https://ejemplo.cl/t.pdf", nivel="02",
)


def transporte(contenido=b"%PDF-1.4 contenido", registro=None):
    def _t(url):
        if registro is not None:
            registro.append(url)
        return contenido, "application/pdf"
    return _t


def test_descarga_y_deja_un_manifiesto_que_se_explica_solo(tmp_path):
    """Una carpeta de PDF sin manifiesto no es una caché, es un montón de PDF."""
    d = descargar(DOC, tmp_path, transporte=transporte())
    guardado = cargar_manifiesto(tmp_path).get("cl-temario-02-basico")
    assert guardado.url == DOC.url
    assert guardado.sha256 == d.sha256
    assert guardado.licencia.tipo == DOC.licencia.tipo
    assert guardado.titulo == "Temario 2º básico"
    assert (tmp_path / "cl-temario-02-basico.pdf").read_bytes() == b"%PDF-1.4 contenido"


def test_la_segunda_vez_no_vuelve_a_pedirlo(tmp_path):
    registro = []
    descargar(DOC, tmp_path, transporte=transporte(registro=registro))
    descargar(DOC, tmp_path, transporte=transporte(registro=registro))
    assert len(registro) == 1


def test_forzar_si_vuelve_a_pedirlo(tmp_path):
    registro = []
    descargar(DOC, tmp_path, transporte=transporte(registro=registro))
    descargar(DOC, tmp_path, forzar=True, transporte=transporte(registro=registro))
    assert len(registro) == 2


def test_un_documento_sin_url_dice_como_meterlo_a_mano(tmp_path):
    sin_url = DOC.model_copy(update={"url": None})
    with pytest.raises(ErrorDescarga, match="adjuntar"):
        descargar(sin_url, tmp_path, transporte=transporte())


def test_adjuntar_mete_un_archivo_local_por_el_mismo_camino(tmp_path):
    """Quien ya tiene el PDF no debería esperar a que se verifique una URL."""
    origen = tmp_path / "articles-18977_programa.pdf"
    origen.write_bytes(b"%PDF-1.4 de mi carpeta de descargas")
    cache = tmp_path / "cache"
    d = adjuntar(DOC.model_copy(update={"id": "cl-programa-matematica", "url": None}),
                 origen, cache)
    assert d.origen == "archivo"
    assert d.url is None
    assert cargar_manifiesto(cache).get("cl-programa-matematica").sha256 == d.sha256


def test_adjuntar_lo_que_no_existe_lo_dice_claro(tmp_path):
    with pytest.raises(ErrorDescarga, match="no encuentro"):
        adjuntar(DOC, tmp_path / "no-existe.pdf", tmp_path / "cache")


def test_un_fallo_no_impide_traer_los_demas(tmp_path):
    """Que el temario de 7º no exista no es motivo para no importar el de 2º."""
    def _falla(url):
        raise ErrorDescarga("404")
    otro = DOC.model_copy(update={"id": "otro", "url": "https://ejemplo.cl/o.pdf"})
    traidas, fallos = traer_todos([DOC, otro], tmp_path,
                                  transporte=lambda url: _falla(url) if "o.pdf" in url
                                  else (b"%PDF ok", "application/pdf"))
    assert [d.id for d in traidas] == ["cl-temario-02-basico"]
    assert fallos[0][0] == "otro"


def test_una_cache_que_viajo_a_medias_se_detecta(tmp_path):
    """Un PDF truncado produce una extracción incompleta en silencio. Peor que un error."""
    descargar(DOC, tmp_path, transporte=transporte())
    assert verificar(tmp_path) == []
    (tmp_path / "cl-temario-02-basico.pdf").write_bytes(b"otra cosa")
    assert "sha256" in verificar(tmp_path)[0]


def test_una_descarga_vacia_no_se_da_por_buena(tmp_path):
    with pytest.raises(ErrorDescarga, match="vacío"):
        descargar(DOC, tmp_path, transporte=transporte(contenido=b""))


def test_el_catalogo_filtra_por_nivel_y_deja_fuera_los_inactivos():
    assert [d.id for d in documentos("CL", nivel="02")] == ["cl-temario-02-basico"]
    assert any(not d.activo for d in documentos("CL", incluir_inactivos=True))


def test_un_pais_sin_catalogo_dice_cuales_hay():
    with pytest.raises(KeyError, match="Disponibles"):
        documentos("XX")


def test_un_documento_desconocido_lista_los_conocidos():
    with pytest.raises(KeyError, match="cl-temario-02-basico"):
        por_id("CL", "no-existe")
