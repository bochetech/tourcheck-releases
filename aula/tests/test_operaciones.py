"""El vocabulario de reparación debe arreglar lo que dice, y rechazar lo demás."""

from __future__ import annotations

import pytest

from aula.curriculum.model import Licencia, Objetivo
from aula.curriculum.operaciones import (
    AgregarItems,
    AgregarObjetivo,
    CorregirPrerequisito,
    FijarCampo,
    FijarFuente,
    FijarLicencia,
    FijarMeta,
    FusionarDuplicados,
    QuitarPrerequisito,
    ReescalarHoras,
    ReescribirTexto,
    aplicar,
    aplicar_una,
)
from factories import curriculo_sano, objetivo


def aplica(curriculum, op):
    """Aplica una operación y devuelve el motivo de rechazo (None si funcionó)."""
    return aplicar_una(curriculum, op)


# ------------------------------------------------------------------ prerequisitos


def test_quitar_prerequisito():
    c = curriculo_sano()
    assert aplica(c, QuitarPrerequisito(objetivo="MA02 OA 02", prerequisito="MA02 OA 01")) is None
    assert c.por_codigo()["MA02 OA 02"].prerequisitos == []


def test_quitar_prerequisito_inexistente_se_rechaza_con_motivo():
    c = curriculo_sano()
    motivo = aplica(c, QuitarPrerequisito(objetivo="MA02 OA 02", prerequisito="MA02 OA 99"))
    assert motivo and "no tiene el prerrequisito" in motivo


def test_corregir_prerequisito_exige_que_el_destino_exista():
    """Si no, se cambiaría una referencia rota por otra."""
    c = curriculo_sano()
    motivo = aplica(c, CorregirPrerequisito(objetivo="MA02 OA 02", de="MA02 OA 01", a="MA02 OA 77"))
    assert motivo and "tampoco existe" in motivo
    assert c.por_codigo()["MA02 OA 02"].prerequisitos == ["MA02 OA 01"]


def test_corregir_prerequisito_impide_la_autorreferencia():
    c = curriculo_sano()
    motivo = aplica(c, CorregirPrerequisito(objetivo="MA02 OA 02", de="MA02 OA 01", a="MA02 OA 02"))
    assert motivo and "sí mismo" in motivo


# ------------------------------------------------------------------------ campos


def test_fijar_campo_rellena_un_huerfano():
    c = curriculo_sano()
    c.objetivos[0].asignatura = ""
    assert aplica(c, FijarCampo(objetivo="MA02 OA 01", campo="asignatura", valor="MA")) is None
    assert c.objetivos[0].asignatura == "MA"


def test_no_se_puede_desmarcar_un_objetivo_del_temario_oficial():
    """El temario es el blanco mínimo: sacarlo de ahí es justo lo que no debe pasar."""
    c = curriculo_sano()
    motivo = aplica(c, FijarCampo(objetivo="MA02 OA 01", campo="en_temario_examen", valor=False))
    assert motivo and "temario oficial" in motivo
    assert c.objetivos[0].en_temario_examen is True


def test_fijar_campo_rechaza_horas_negativas():
    c = curriculo_sano()
    motivo = aplica(c, FijarCampo(objetivo="MA02 OA 01", campo="horas_estimadas", valor=-3))
    assert motivo and "negativas" in motivo


def test_fijar_campo_rechaza_un_valor_vacio():
    c = curriculo_sano()
    assert aplica(c, FijarCampo(objetivo="MA02 OA 01", campo="unidad", valor="   ")) is not None


# ------------------------------------------------------- ítems, fuente, licencia


def test_agregar_items_no_duplica():
    c = curriculo_sano()
    assert aplica(c, AgregarItems(objetivo="MA02 OA 01", items=["nuevo"])) is None
    motivo = aplica(c, AgregarItems(objetivo="MA02 OA 01", items=["nuevo"]))
    assert motivo and "nuevo" in motivo
    assert c.objetivos[0].items.count("nuevo") == 1


def test_fijar_fuente_exige_documento():
    c = curriculo_sano()
    assert aplica(c, FijarFuente(objetivo="MA02 OA 01", doc="  ")) is not None
    assert aplica(c, FijarFuente(objetivo="MA02 OA 01", doc="Temario", pagina=4)) is None
    assert c.objetivos[0].fuente.pagina == 4


def test_fijar_licencia_no_acepta_desconocida():
    """Declarar «desconocida» no es declarar nada."""
    c = curriculo_sano()
    c.objetivos[0].licencia = Licencia()
    assert aplica(c, FijarLicencia(objetivo="MA02 OA 01", tipo="desconocida")) is not None
    assert aplica(c, FijarLicencia(objetivo="MA02 OA 01", tipo="CC-BY-SA")) is None


# ------------------------------------------------------------------------ textos


def test_reescribir_texto_conserva_el_oficial():
    """El texto del ministerio no se puede perder al simplificarlo para el niño."""
    c = curriculo_sano()
    original = c.objetivos[0].texto
    c.objetivos[0].resumen = None
    assert aplica(c, ReescribirTexto(objetivo="MA02 OA 01", texto="Cuenta hasta cien.")) is None
    assert c.objetivos[0].texto == "Cuenta hasta cien."
    assert c.objetivos[0].resumen == original


def test_reescribir_texto_rechaza_un_texto_ridiculamente_corto():
    c = curriculo_sano()
    assert aplica(c, ReescribirTexto(objetivo="MA02 OA 01", texto="Sumar")) is not None


# ------------------------------------------------------------------------- horas


def test_reescalar_horas_aplica_el_factor_a_toda_la_asignatura():
    c = curriculo_sano()
    assert aplica(c, ReescalarHoras(nivel="02", asignatura="MA", factor=0.5)) is None
    assert [o.horas_estimadas for o in c.objetivos] == [10.0, 10.0, 10.0]


@pytest.mark.parametrize("factor", [0.0, -2.0, 500.0])
def test_reescalar_horas_rechaza_factores_absurdos(factor):
    c = curriculo_sano()
    assert aplica(c, ReescalarHoras(nivel="02", asignatura="MA", factor=factor)) is not None


def test_reescalar_horas_avisa_si_no_hay_objetivos_de_esa_asignatura():
    c = curriculo_sano()
    motivo = aplica(c, ReescalarHoras(nivel="02", asignatura="LE", factor=2))
    assert motivo and "no hay objetivos" in motivo


# -------------------------------------------------------------------- duplicados


def test_fusionar_duplicados_une_prerrequisitos_e_items():
    c = curriculo_sano()
    gemelo = objetivo("MA02 OA 01", "Contar numeros hasta el cien.",
                      prerequisitos=["MA02 OA 02"], items=["extra"])
    gemelo.confianza = 0.4
    c.objetivos.append(gemelo)

    assert aplica(c, FusionarDuplicados(codigo="MA02 OA 01")) is None

    supervivientes = [o for o in c.objetivos if o.codigo == "MA02 OA 01"]
    assert len(supervivientes) == 1
    assert "extra" in supervivientes[0].items
    assert "MA02 OA 02" in supervivientes[0].prerequisitos
    # Sobrevive la copia de mayor confianza.
    assert supervivientes[0].confianza == 0.95


def test_fusionar_lo_que_no_esta_duplicado_se_rechaza():
    c = curriculo_sano()
    assert aplica(c, FusionarDuplicados(codigo="MA02 OA 01")) is not None


# ---------------------------------------------------------------------- agregado


def test_agregar_objetivo_que_falta_del_temario():
    c = curriculo_sano()
    nuevo = objetivo("MA02 OA 04", "Comparar dos numeros y decir cual es mayor.")
    assert aplica(c, AgregarObjetivo(objetivo=nuevo)) is None
    assert "MA02 OA 04" in c.por_codigo()


def test_agregar_un_objetivo_que_ya_existe_se_rechaza():
    c = curriculo_sano()
    repetido = objetivo("MA02 OA 01", "Contar numeros hasta el cien.")
    assert aplica(c, AgregarObjetivo(objetivo=repetido)) is not None


# -------------------------------------------------------------------- metadatos


def test_fijar_meta_completa_la_version():
    c = curriculo_sano()
    c.version = ""
    assert aplica(c, FijarMeta(campo="version", valor="2026-03")) is None
    assert c.version == "2026-03"


# ------------------------------------------------------------------ tanda entera


def test_aplicar_reporta_cada_operacion_por_separado():
    """El bucle necesita saber cuáles entraron y por qué fallaron las otras."""
    c = curriculo_sano()
    resultado = aplicar(c, [
        QuitarPrerequisito(objetivo="MA02 OA 02", prerequisito="MA02 OA 01"),
        QuitarPrerequisito(objetivo="MA02 OA 02", prerequisito="FANTASMA"),
    ])
    assert [a.aplicada for a in resultado] == [True, False]
    assert resultado[1].rechazo
    assert resultado[0].operacion["op"] == "quitar_prerequisito"
