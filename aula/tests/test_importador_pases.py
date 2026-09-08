"""Los tres pases globales, y sobre todo lo que rechazan."""

from __future__ import annotations

from aula.curriculum.model import Curriculum, FuenteCurriculo, Objetivo
from aula.importador.pases import (
    enriquecer,
    pase_items,
    pase_prerequisitos,
    pase_resumenes,
)
from falso_llm import ModeloDeMentira, cliente_falso


def curriculo(n: int = 4) -> Curriculum:
    return Curriculum(
        id="cl-test",
        version="2026-03",
        fuente=FuenteCurriculo(pais="CL", organismo="MINEDUC"),
        objetivos=[
            Objetivo(
                codigo=f"MA02 OA {i:02d}",
                texto=f"Objetivo numero {i} redactado con normalidad.",
                asignatura="MA",
                nivel="02",
            )
            for i in range(1, n + 1)
        ],
    )


def test_los_prerrequisitos_se_encadenan_y_no_mutan_el_original():
    original = curriculo(4)
    nuevo, informe = pase_prerequisitos(original, cliente_falso(ModeloDeMentira()))
    assert informe.aplicados == 3
    assert nuevo.por_codigo()["MA02 OA 02"].prerequisitos == ["MA02 OA 01"]
    assert all(not o.prerequisitos for o in original.objetivos)


def test_una_arista_que_cerraria_un_ciclo_se_rechaza_aqui_y_no_despues():
    """Detectado aquí cuesta una línea; detectado después, una vuelta de modelo."""
    class Ciclico(ModeloDeMentira):
        def _prerrequisitos(self, texto):
            return (
                '{"aristas": [{"objetivo": "MA02 OA 02", "requiere": "MA02 OA 01"},'
                ' {"objetivo": "MA02 OA 01", "requiere": "MA02 OA 02"}]}'
            )

    nuevo, informe = pase_prerequisitos(curriculo(2), cliente_falso(Ciclico()))
    assert informe.aplicados == 1
    assert any("ciclo" in r for r in informe.rechazados)


def test_un_objetivo_no_puede_requerirse_a_si_mismo():
    class Narcisista(ModeloDeMentira):
        def _prerrequisitos(self, texto):
            return '{"aristas": [{"objetivo": "MA02 OA 01", "requiere": "MA02 OA 01"}]}'

    _, informe = pase_prerequisitos(curriculo(2), cliente_falso(Narcisista()))
    assert informe.aplicados == 0
    assert "sí mismo" in informe.rechazados[0]


def test_un_codigo_fuera_de_la_tanda_se_rechaza():
    class Inventor(ModeloDeMentira):
        def _prerrequisitos(self, texto):
            return '{"aristas": [{"objetivo": "MA02 OA 01", "requiere": "ZZ99 OA 99"}]}'

    _, informe = pase_prerequisitos(curriculo(2), cliente_falso(Inventor()))
    assert informe.aplicados == 0
    assert "fuera de la tanda" in informe.rechazados[0]


def test_los_resumenes_son_el_indice_rag_y_van_a_todos_los_objetivos():
    nuevo, informe = pase_resumenes(curriculo(10), cliente_falso(ModeloDeMentira()))
    assert informe.aplicados == 10
    assert informe.pendientes == []
    assert all(o.resumen for o in nuevo.objetivos)


def test_no_se_reescribe_un_resumen_que_ya_existe():
    base = curriculo(2)
    base.objetivos[0].resumen = "Escrito a mano por una persona."
    modelo = ModeloDeMentira()
    nuevo, _ = pase_resumenes(base, cliente_falso(modelo))
    assert nuevo.objetivos[0].resumen == "Escrito a mano por una persona."
    assert len(modelo.llamadas) == 1  # solo se preguntó por el que faltaba


def test_cada_objetivo_acaba_con_al_menos_un_item():
    """Es lo que exige la regla 4: lo que no se puede evaluar no se puede dominar."""
    nuevo, informe = pase_items(curriculo(7), cliente_falso(ModeloDeMentira()))
    assert all(len(o.items) >= 1 for o in nuevo.objetivos)
    assert informe.pendientes == []


def test_lo_que_no_se_pudo_cubrir_queda_dicho_en_vez_de_pasar_desapercibido():
    _, informe = pase_items(curriculo(3), cliente_falso(ModeloDeMentira(sin_items=True)))
    assert sorted(informe.pendientes) == ["MA02 OA 01", "MA02 OA 02", "MA02 OA 03"]


def test_los_tres_pases_seguidos_dejan_el_curriculo_completo():
    modelo = ModeloDeMentira()
    cliente = cliente_falso(modelo)
    nuevo, informes = enriquecer(curriculo(5), cliente, cliente, cliente)
    assert [i.pase for i in informes] == ["prerrequisitos", "resumenes", "items"]
    assert all(o.resumen and o.items for o in nuevo.objetivos)
