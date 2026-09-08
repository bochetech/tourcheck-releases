"""Familias, estudiantes y planes: multi-estudiante desde el primer día."""

from __future__ import annotations

import datetime as dt

import pytest

from aula.familia import (
    Adulto,
    Asignacion,
    Estudiante,
    Familia,
    ModoUI,
    PerfilVoz,
    cargar_familia,
    guardar_familia,
)

HOY = dt.date(2026, 9, 8)


def nino(nombre="Mateo", nacimiento=dt.date(2019, 4, 10), **extra) -> Estudiante:
    return Estudiante(nombre=nombre, nacimiento=nacimiento, **extra)


def familia_con_dos() -> Familia:
    f = Familia(nombre="Familia Villanueva")
    f.agregar_adulto(Adulto(nombre="Carlos"))
    f.agregar_estudiante(nino("Mateo", dt.date(2019, 4, 10)))
    f.agregar_estudiante(nino("Sofía", dt.date(2013, 7, 2)))
    return f


# ------------------------------------------------------------- identificadores


def test_el_id_sale_del_nombre_sin_acentos():
    """Para poder escribir `aula familia asignar sofia` sin pelear con la tilde."""
    assert nino("Sofía").id == "sofia"
    assert nino("José Ignacio").id == "jose-ignacio"


def test_se_puede_buscar_por_nombre_con_o_sin_tilde():
    f = familia_con_dos()
    assert f.estudiante("Sofía").id == f.estudiante("sofia").id


def test_buscar_a_quien_no_existe_dice_quienes_hay():
    f = familia_con_dos()
    with pytest.raises(KeyError, match="mateo, sofia"):
        f.estudiante("Pedro")


# ------------------------------------------------------------------ edad y piel


def test_la_edad_cuenta_bien_el_cumpleanos_que_no_ha_llegado():
    assert nino(nacimiento=dt.date(2019, 12, 25)).edad(HOY) == 6
    assert nino(nacimiento=dt.date(2019, 4, 10)).edad(HOY) == 7


def test_la_piel_la_decide_la_edad_por_defecto():
    assert nino(nacimiento=dt.date(2019, 4, 10)).modo_efectivo(HOY) is ModoUI.EXPLORADOR
    assert nino(nacimiento=dt.date(2013, 7, 2)).modo_efectivo(HOY) is ModoUI.TALLER


def test_un_adulto_puede_fijar_la_piel_a_mano():
    """Un niño de 11 con dificultades de lectura puede necesitar Explorador."""
    grande = nino(nacimiento=dt.date(2015, 1, 1), modo_ui=ModoUI.EXPLORADOR)
    assert grande.modo_efectivo(HOY) is ModoUI.EXPLORADOR
    assert grande.voz_efectiva(HOY) is PerfilVoz.RESTRINGIDA


def test_la_voz_sigue_a_la_piel_porque_el_reconocimiento_falla_con_los_pequenos():
    assert nino(nacimiento=dt.date(2019, 4, 10)).voz_efectiva(HOY) is PerfilVoz.RESTRINGIDA
    assert nino(nacimiento=dt.date(2013, 7, 2)).voz_efectiva(HOY) is PerfilVoz.ABIERTA


def test_la_voz_tambien_se_puede_fijar_aparte():
    terco = nino(nacimiento=dt.date(2019, 4, 10), perfil_voz=PerfilVoz.ABIERTA)
    assert terco.modo_efectivo(HOY) is ModoUI.EXPLORADOR
    assert terco.voz_efectiva(HOY) is PerfilVoz.ABIERTA


# ------------------------------------------------------------------ asignación


def test_asignar_un_plan_lo_fija_a_una_version():
    e = nino()
    e.asignar(Asignacion(curriculum_id="cl-mineduc-2026", version="2026-03", nivel="02"))
    assert e.asignacion.version == "2026-03"
    assert e.historial == []


def test_migrar_de_version_guarda_la_anterior_en_el_historial():
    """El currículo chileno está en disputa: hay que poder mirar atrás."""
    e = nino()
    e.asignar(Asignacion(curriculum_id="cl", version="2026-03", nivel="02"))
    e.asignar(Asignacion(curriculum_id="cl", version="2027-01", nivel="03",
                         nota="estructura 6+6"))

    assert e.asignacion.version == "2027-01"
    assert [a.version for a in e.historial] == ["2026-03"]
    assert e.asignacion.nota == "estructura 6+6"


def test_reasignar_exactamente_lo_mismo_se_rechaza():
    """Evita ensuciar el historial con migraciones que no migran nada."""
    e = nino()
    plan = Asignacion(curriculum_id="cl", version="2026-03", nivel="02")
    e.asignar(plan)
    with pytest.raises(ValueError, match="ya tiene asignado"):
        e.asignar(Asignacion(curriculum_id="cl", version="2026-03", nivel="02"))


def test_cambiar_solo_de_nivel_si_es_una_migracion():
    e = nino()
    e.asignar(Asignacion(curriculum_id="cl", version="2026-03", nivel="02"))
    e.asignar(Asignacion(curriculum_id="cl", version="2026-03", nivel="03"))
    assert len(e.historial) == 1


# ------------------------------------------------------------------- la familia


def test_no_se_pueden_repetir_estudiantes():
    f = familia_con_dos()
    with pytest.raises(ValueError, match="ya hay un estudiante"):
        f.agregar_estudiante(nino("Mateo"))


def test_no_se_pueden_repetir_adultos():
    f = familia_con_dos()
    with pytest.raises(ValueError, match="ya hay un adulto"):
        f.agregar_adulto(Adulto(nombre="Carlos"))


def test_el_tope_conjunto_suma_el_de_cada_uno():
    f = familia_con_dos()
    f.estudiante("mateo").presupuesto_mensual_usd = 4.0
    f.estudiante("sofia").presupuesto_mensual_usd = 6.5
    assert f.presupuesto_total_usd == 10.5


def test_el_presupuesto_no_puede_ser_negativo():
    with pytest.raises(ValueError, match="no puede ser negativo"):
        nino(presupuesto_mensual_usd=-1)


def test_una_familia_nace_vacia_y_es_valida():
    f = Familia(nombre="Los Pérez")
    assert f.id == "los-perez"
    assert f.estudiantes == [] and f.presupuesto_total_usd == 0


# ---------------------------------------------------------------- persistencia


def test_guardar_y_volver_a_leer_conserva_todo(tmp_path):
    f = familia_con_dos()
    f.estudiante("mateo").asignar(
        Asignacion(curriculum_id="cl", version="2026-03", nivel="02"))
    f.estudiante("mateo").asignar(
        Asignacion(curriculum_id="cl", version="2027-01", nivel="03"))
    f.estudiante("sofia").nombre_companero = "Nube"

    ruta = guardar_familia(f, tmp_path / "familia.yaml")
    leida = cargar_familia(ruta)

    assert leida.nombre == f.nombre
    assert leida.estudiante("mateo").asignacion.version == "2027-01"
    assert len(leida.estudiante("mateo").historial) == 1
    assert leida.estudiante("sofia").nombre_companero == "Nube"
    assert leida.estudiante("mateo").nacimiento == dt.date(2019, 4, 10)


def test_leer_una_familia_que_no_existe_dice_como_crearla(tmp_path):
    with pytest.raises(FileNotFoundError, match="aula familia crear"):
        cargar_familia(tmp_path / "no-existe.yaml")


def test_el_compañero_lo_puede_nombrar_el_nino():
    """Nombrar al compañero es lo que crea el vínculo; «Copi» es solo el defecto."""
    assert nino().nombre_companero == "Copi"
    assert nino(nombre_companero="Tuka").nombre_companero == "Tuka"
