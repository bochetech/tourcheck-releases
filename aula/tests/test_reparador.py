"""El bucle de auto-reparación: cierra lo que puede y nunca degrada el plan."""

from __future__ import annotations

from aula.curriculum.operaciones import (
    AgregarItems,
    FijarFuente,
    QuitarPrerequisito,
    ReescribirTexto,
)
from aula.curriculum.reparador import reparar
from aula.curriculum.validator import validar
from factories import curriculo_sano


def proponente_competente(curriculum, hallazgos, rechazos):
    """Un proponente que sabe arreglar lo que el validador reporta."""
    ops = []
    for h in hallazgos:
        if h.codigo_regla == "R01_CICLO":
            ciclo = h.datos["ciclo"]
            ops.append(QuitarPrerequisito(objetivo=ciclo[0], prerequisito=ciclo[1]))
        elif h.codigo_regla == "R02_PREREQ_INEXISTENTE":
            ops.append(QuitarPrerequisito(
                objetivo=h.datos["objetivo"], prerequisito=h.datos["prerequisito_roto"]))
        elif h.codigo_regla == "R04_SIN_ITEMS":
            ops.append(AgregarItems(objetivo=h.objetivo, items=[f"{h.objetivo}-generado"]))
        elif h.codigo_regla == "R05_SIN_FUENTE":
            ops.append(FijarFuente(objetivo=h.objetivo, doc="Temario 2 basico", pagina=3))
    return ops


def proponente_inutil(curriculum, hallazgos, rechazos):
    """Propone algo que el código siempre rechaza: no avanza nunca."""
    return [QuitarPrerequisito(objetivo="NO EXISTE", prerequisito="TAMPOCO")]


def proponente_rendido(curriculum, hallazgos, rechazos):
    """No sabe qué hacer. Lo que queda es para el padre."""
    return []


def proponente_destructivo(curriculum, hallazgos, rechazos):
    """No arregla nada y estropea dos textos: la vuelta debe descartarse entera."""
    ilegible = ("Conceptualizar representaciones numericas polivalentes mediante "
                "procedimientos algoritmicos sistematizados interdisciplinariamente.")
    return [ReescribirTexto(objetivo=codigo, texto=ilegible)
            for codigo in ("MA02 OA 01", "MA02 OA 03")]


# ------------------------------------------------------------------- caso feliz


def test_cierra_solo_todo_lo_que_puede():
    c = curriculo_sano()
    c.objetivos[0].prerequisitos = ["MA02 OA 03"]  # ciclo
    c.objetivos[1].items = []                       # sin evaluación
    c.objetivos[2].fuente = None                    # sin trazabilidad

    reparado, reparacion = reparar(c, proponente_competente)

    assert reparacion.ok
    assert reparacion.pendientes_para_el_padre == []
    assert validar(reparado).hallazgos == []


def test_no_toca_el_curriculo_original():
    """El bucle trabaja sobre una copia: si sale mal, no se llevó nada por delante."""
    c = curriculo_sano()
    c.objetivos[1].items = []

    reparar(c, proponente_competente)

    assert c.objetivos[1].items == []


def test_un_curriculo_sano_no_gasta_ni_una_vuelta():
    reparado, reparacion = reparar(curriculo_sano(), proponente_competente)
    assert reparacion.vueltas == []
    assert reparacion.ok


# --------------------------------------------------- la propiedad que más importa


def test_una_vuelta_que_empeora_el_plan_se_descarta_entera():
    """Un bucle que puede degradar el currículo es peor que no tener bucle."""
    c = curriculo_sano()
    c.objetivos[1].items = []
    antes = validar(c)

    reparado, reparacion = reparar(c, proponente_destructivo)

    vuelta = reparacion.vueltas[0]
    assert vuelta.adoptada is False
    assert "no mejoró" in vuelta.motivo
    # El plan que sale es exactamente el que entró: ni el parche bueno se cuela.
    assert validar(reparado).hallazgos == antes.hallazgos
    assert reparado.por_codigo()["MA02 OA 02"].items == []


# ----------------------------------------------------------------- casos límite


def test_se_detiene_cuando_el_proponente_se_rinde():
    c = curriculo_sano()
    c.objetivos[1].items = []

    _, reparacion = reparar(c, proponente_rendido)

    assert reparacion.vueltas == []
    assert not reparacion.ok
    assert any(h.codigo_regla == "R04_SIN_ITEMS" for h in reparacion.pendientes_para_el_padre)


def test_no_se_queda_dando_vueltas_si_nada_se_aplica():
    c = curriculo_sano()
    c.objetivos[1].items = []

    _, reparacion = reparar(c, proponente_inutil, max_vueltas=10)

    assert len(reparacion.vueltas) == 1
    assert reparacion.vueltas[0].adoptada is False


def test_respeta_el_tope_de_vueltas():
    c = curriculo_sano()
    for objetivo in c.objetivos:
        objetivo.items = []

    def de_a_uno(curriculum, hallazgos, rechazos):
        for h in hallazgos:
            if h.codigo_regla == "R04_SIN_ITEMS":
                return [AgregarItems(objetivo=h.objetivo, items=["i"])]
        return []

    _, reparacion = reparar(c, de_a_uno, max_vueltas=2)

    assert len(reparacion.vueltas) == 2
    assert not reparacion.ok  # quedaba un tercero sin ítems


def test_los_rechazos_vuelven_como_retroalimentacion():
    """El proponente debe enterarse de por qué le rechazaron algo."""
    vistos = []

    def observador(curriculum, hallazgos, rechazos):
        vistos.append(list(rechazos))
        # Arregla un hallazgo por vuelta, y en la primera cuela una operación mala.
        ops = []
        for h in hallazgos:
            if h.codigo_regla == "R04_SIN_ITEMS":
                ops.append(AgregarItems(objetivo=h.objetivo, items=["i"]))
                break
        if len(vistos) == 1:
            ops.append(QuitarPrerequisito(objetivo="FANTASMA", prerequisito="X"))
        return ops

    c = curriculo_sano()
    c.objetivos[0].items = []
    c.objetivos[1].items = []
    reparar(c, observador, max_vueltas=3)

    assert len(vistos) >= 2
    assert vistos[0] == []
    assert any("FANTASMA" in (r.rechazo or "") for r in vistos[1])


def test_la_bitacora_cuenta_lo_que_paso():
    c = curriculo_sano()
    c.objetivos[1].items = []

    _, reparacion = reparar(c, proponente_competente)

    vuelta = reparacion.vueltas[0]
    assert vuelta.bloqueantes_antes == 1
    assert vuelta.bloqueantes_despues == 0
    assert vuelta.adoptada
    assert "cerrados solos" in reparacion.resumen()
