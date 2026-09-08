"""El proponente con modelo: nada de lo que devuelve se cree a ciegas."""

from __future__ import annotations

import json

from aula.config import ModeloConfig, Proveedor
from aula.curriculum.proponente import ProponenteConModelo, esquema_de_propuesta
from aula.curriculum.reparador import reparar
from aula.curriculum.validator import validar
from aula.llm.cliente import Cliente, ErrorLLM
from factories import curriculo_sano

LOCAL = Proveedor(id="lmstudio", base_url="http://127.0.0.1:1234/v1", apto_para_menores=True)


def cliente_que_responde(contenido, registro=None):
    def t(url, cuerpo, cabeceras, limite):
        if registro is not None:
            registro.append(cuerpo)
        return {"choices": [{"message": {"content": contenido}}]}
    return Cliente(LOCAL, ModeloConfig(proveedor="lmstudio", modelo="gemma"), transporte=t)


def cliente_caido():
    def t(url, cuerpo, cabeceras, limite):
        raise ErrorLLM("no se pudo conectar: Connection refused")
    return Cliente(LOCAL, ModeloConfig(proveedor="lmstudio", modelo="gemma"), transporte=t)


# ------------------------------------------------------------------- el esquema


def test_el_esquema_cubre_todo_el_vocabulario():
    defs = esquema_de_propuesta()["$defs"]
    ops = {d["properties"]["op"]["const"] for d in defs.values() if "op" in d.get("properties", {})}
    assert "quitar_prerequisito" in ops and "reescalar_horas" in ops


def test_recortar_el_esquema_quita_agregar_objetivo():
    """Esa operación duplica el tamaño y es la más arriesgada."""
    assert "AgregarObjetivo" in esquema_de_propuesta(True)["$defs"]
    assert "AgregarObjetivo" not in esquema_de_propuesta(False)["$defs"]
    assert len(json.dumps(esquema_de_propuesta(False))) < len(json.dumps(esquema_de_propuesta(True)))


def test_el_esquema_no_arrastra_razonamiento_interno():
    """Todo lo que entra en el esquema se le manda al modelo y le come contexto."""
    completo = json.dumps(esquema_de_propuesta())
    assert "presupuesto de contexto" not in completo
    assert "arriesgada" not in completo


def test_los_objetos_del_esquema_quedan_cerrados():
    """Varios servidores lo exigen en modo estricto."""
    esquema = esquema_de_propuesta()
    for definicion in esquema["$defs"].values():
        if definicion.get("type") == "object":
            assert definicion["additionalProperties"] is False


# ------------------------------------------------------------------- el contexto


def test_al_modelo_se_le_mandan_los_hallazgos_y_no_el_curriculo():
    """El contexto tiene que ser diminuto para que un 7-12B rinda."""
    registro = []
    proponente = ProponenteConModelo(cliente_que_responde('{"operaciones": []}', registro))
    c = curriculo_sano()
    c.objetivos[0].items = []

    proponente(c, validar(c).hallazgos, [])

    enviado = registro[0]["messages"][1]["content"]
    assert "R04_SIN_ITEMS" in enviado
    # El texto de los objetivos que no tienen hallazgos no viaja.
    assert "Restar numeros de dos cifras" not in enviado


def test_los_rechazos_previos_viajan_como_retroalimentacion():
    from aula.curriculum.operaciones import Aplicacion

    registro = []
    proponente = ProponenteConModelo(cliente_que_responde('{"operaciones": []}', registro))
    rechazo = Aplicacion(operacion={"op": "quitar_prerequisito"}, aplicada=False,
                         rechazo="'X' no existe")

    proponente(curriculo_sano(), [], [rechazo])

    assert "no existe" in registro[0]["messages"][1]["content"]


# ------------------------------------------------------- lo que vuelve del modelo


def test_interpreta_operaciones_bien_formadas():
    respuesta = json.dumps({"operaciones": [
        {"op": "agregar_items", "objetivo": "MA02 OA 01", "items": ["i1"]}
    ]})
    ops = ProponenteConModelo(cliente_que_responde(respuesta))(curriculo_sano(), [], [])
    assert len(ops) == 1 and ops[0].op == "agregar_items"


def test_una_operacion_mal_formada_no_tira_las_buenas():
    """Que el modelo se equivoque en la tercera no puede invalidar las dos primeras."""
    respuesta = json.dumps({"operaciones": [
        {"op": "agregar_items", "objetivo": "MA02 OA 01", "items": ["i1"]},
        {"op": "operacion_inventada", "cosa": 1},
        {"op": "fijar_meta", "campo": "version", "valor": "2026-03"},
    ]})
    proponente = ProponenteConModelo(cliente_que_responde(respuesta))
    ops = proponente(curriculo_sano(), [], [])

    assert [o.op for o in ops] == ["agregar_items", "fijar_meta"]
    assert "1 operaciones mal formadas" in proponente.ultimo_error


def test_acepta_que_el_modelo_devuelva_una_lista_pelada():
    respuesta = json.dumps([{"op": "fijar_meta", "campo": "version", "valor": "x"}])
    ops = ProponenteConModelo(cliente_que_responde(respuesta))(curriculo_sano(), [], [])
    assert len(ops) == 1


def test_una_respuesta_sin_sentido_no_propone_nada():
    ops = ProponenteConModelo(cliente_que_responde('"hola"'))(curriculo_sano(), [], [])
    assert ops == []


def test_si_el_modelo_no_responde_no_se_rompe_nada():
    """Sin modelo no hay reparación, pero el plan sigue intacto y se puede revisar."""
    proponente = ProponenteConModelo(cliente_caido())
    c = curriculo_sano()
    c.objetivos[0].items = []

    reparado, reparacion = reparar(c, proponente)

    assert reparacion.vueltas == []
    assert not reparacion.ok
    assert "Connection refused" in proponente.ultimo_error
    assert reparado.objetivos[0].items == []


# ------------------------------------------------------------ de punta a punta


def test_el_bucle_completo_con_un_modelo_simulado():
    """Hallazgos -> el modelo propone -> el código valida y aplica -> plan sano."""
    c = curriculo_sano()
    c.objetivos[1].items = []
    c.objetivos[2].fuente = None

    guiones = iter([
        json.dumps({"operaciones": [
            {"op": "agregar_items", "objetivo": "MA02 OA 02", "items": ["MA02-OA-02-i1"]},
            {"op": "fijar_fuente", "objetivo": "MA02 OA 03", "doc": "Temario 2 basico", "pagina": 3},
            {"op": "quitar_prerequisito", "objetivo": "FANTASMA", "prerequisito": "X"},
        ]}),
        json.dumps({"operaciones": []}),
    ])

    def t(url, cuerpo, cabeceras, limite):
        return {"choices": [{"message": {"content": next(guiones)}}]}

    cliente = Cliente(LOCAL, ModeloConfig(proveedor="lmstudio", modelo="gemma"), transporte=t)
    reparado, reparacion = reparar(c, ProponenteConModelo(cliente))

    assert reparacion.ok
    assert validar(reparado).hallazgos == []
    # La operación inventada se rechazó sin frenar a las otras dos.
    rechazadas = [a for a in reparacion.vueltas[0].aplicaciones if not a.aplicada]
    assert len(rechazadas) == 1 and "FANTASMA" in rechazadas[0].rechazo
