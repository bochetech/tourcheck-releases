"""Confianza a partir de señales computables, no de la opinión del modelo."""

from __future__ import annotations

from aula.curriculum.model import Fuente, Licencia
from aula.importador.consolidar import (
    PENA_CONFLICTO,
    consolidar,
    construir_curriculum,
)
from aula.importador.extraccion import ObjetivoExtraido
from aula.curriculum.model import FuenteCurriculo

FUENTE = Fuente(doc="Temario 2 basico", pagina=3, url="https://ejemplo.cl/t.pdf")
TEXTO = "Contar numeros hasta el cien de uno en uno con material concreto."
EN_FUENTE = {"MA02 OA 01", "MA02 OA 02", "MA02 OA 03"}


def extraido(codigo, texto=TEXTO, trozo=1, **extra):
    return ObjetivoExtraido(
        codigo=codigo, texto=texto, asignatura="MA", nivel="02",
        fuente=FUENTE, doc_id="d", trozo=trozo, **extra
    )


def test_el_que_aparece_en_dos_trozos_puntua_mas_que_el_que_aparece_en_uno():
    """El solape del troceado existe justamente para producir esta señal."""
    c = consolidar(
        [extraido("MA02 OA 01", trozo=1), extraido("MA02 OA 01", trozo=2),
         extraido("MA02 OA 02", trozo=1)],
        codigos_en_fuente=EN_FUENTE, nivel_documento="02",
    )
    por_codigo = {o.codigo: o.confianza for o in c.objetivos}
    assert por_codigo["MA02 OA 01"] > por_codigo["MA02 OA 02"]


def test_un_codigo_que_no_esta_en_el_documento_se_descarta_gane_lo_que_gane():
    """Pesa más aparecer en la fuente que cualquier otra señal junta."""
    c = consolidar(
        [extraido("MA02 OA 01"), extraido("XX99 OA 99", trozo=1),
         extraido("XX99 OA 99", trozo=2)],
        codigos_en_fuente=EN_FUENTE,
    )
    assert [o.codigo for o in c.objetivos] == ["MA02 OA 01"]
    assert "inventado" in c.descartados["XX99 OA 99"]


def test_dos_textos_distintos_para_el_mismo_codigo_se_marcan_y_penalizan():
    c = consolidar(
        [extraido("MA02 OA 01", texto=TEXTO, trozo=1),
         extraido("MA02 OA 01", texto="Otra cosa completamente distinta.", trozo=2)],
        codigos_en_fuente=EN_FUENTE, nivel_documento="02",
    )
    limpio = consolidar([extraido("MA02 OA 01")], codigos_en_fuente=EN_FUENTE,
                        nivel_documento="02")
    assert c.conflictos[0].codigo == "MA02 OA 01"
    assert c.objetivos[0].confianza < limpio.objetivos[0].confianza
    assert limpio.objetivos[0].confianza - c.objetivos[0].confianza >= PENA_CONFLICTO - 0.01


def test_ante_un_conflicto_gana_el_texto_mas_repetido():
    c = consolidar(
        [extraido("MA02 OA 01", texto=TEXTO, trozo=1),
         extraido("MA02 OA 01", texto=TEXTO, trozo=2),
         extraido("MA02 OA 01", texto="Version corta.", trozo=3)],
        codigos_en_fuente=EN_FUENTE,
    )
    assert c.objetivos[0].texto == TEXTO


def test_a_igualdad_de_repeticiones_gana_el_texto_mas_largo():
    """Un objetivo truncado en la frontera de un trozo siempre es el corto."""
    c = consolidar(
        [extraido("MA02 OA 01", texto=TEXTO, trozo=1),
         extraido("MA02 OA 01", texto="Contar numeros hasta", trozo=2)],
        codigos_en_fuente=EN_FUENTE,
    )
    assert c.objetivos[0].texto == TEXTO


def test_los_dudosos_son_los_que_hay_que_mirar_a_mano():
    c = consolidar(
        [extraido("MA02 OA 01", texto="corto", trozo=1)],
        codigos_en_fuente=EN_FUENTE, nivel_documento="09",
    )
    assert c.objetivos[0].confianza < 0.7
    assert [o.codigo for o in c.dudosos] == ["MA02 OA 01"]


def test_el_temario_importado_hace_que_la_regla_6_pase_por_construccion():
    """El documento *es* la lista oficial de lo que se evalúa. No es un atajo."""
    c = consolidar([extraido("MA02 OA 01"), extraido("MA02 OA 02")],
                   codigos_en_fuente=EN_FUENTE, nivel_documento="02")
    curriculo = construir_curriculum(
        c, id_curriculo="cl-test", version="2026-03",
        fuente=FuenteCurriculo(pais="CL", organismo="MINEDUC"),
        licencia=Licencia(tipo="CC-BY-SA", puede_redistribuir=True), es_temario=True,
    )
    assert curriculo.temario == {"02": ["MA02 OA 01", "MA02 OA 02"]}
    assert all(o.en_temario_examen for o in curriculo.objetivos)
    assert all(o.licencia.tipo == "CC-BY-SA" for o in curriculo.objetivos)


def test_un_programa_de_estudio_no_declara_temario():
    c = consolidar([extraido("MA02 OA 01")], codigos_en_fuente=EN_FUENTE)
    curriculo = construir_curriculum(
        c, id_curriculo="cl-test", version="2026-03",
        fuente=FuenteCurriculo(pais="CL", organismo="MINEDUC"), es_temario=False,
    )
    assert curriculo.temario == {}
    assert not curriculo.objetivos[0].en_temario_examen
