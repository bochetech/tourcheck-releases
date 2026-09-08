"""El cliente de modelos: sin salir a la red, con un transporte inyectado."""

from __future__ import annotations

import pytest

from aula.config import ModeloConfig, Proveedor
from aula.llm.cliente import Cliente, ErrorLLM


def transporte(respuestas, registro=None):
    """Devuelve un transporte falso que sirve respuestas preparadas."""
    def _t(url, cuerpo, cabeceras, limite):
        if registro is not None:
            registro.append({"url": url, "cuerpo": cuerpo, "cabeceras": cabeceras})
        clave = "models" if url.endswith("/models") else "chat"
        valor = respuestas[clave]
        if isinstance(valor, Exception):
            raise valor
        return valor
    return _t


LOCAL = Proveedor(id="lmstudio", base_url="http://127.0.0.1:1234/v1",
                  api_key_env="LMSTUDIO_API_KEY", apto_para_menores=True)
NUBE = Proveedor(id="openai", base_url="https://api.openai.com/v1",
                 api_key_env="OPENAI_API_KEY", apto_para_menores=True)

CHAT_OK = {"model": "gemma", "choices": [{"message": {"content": '{"ok": true}'}}],
           "usage": {"prompt_tokens": 12, "completion_tokens": 5}}
MODELOS_OK = {"data": [{"id": "google/gemma-4-12b"}, {"id": "otro/modelo"}]}


def cliente(modelo="auto", proveedor=LOCAL, respuestas=None, registro=None):
    respuestas = respuestas or {"models": MODELOS_OK, "chat": CHAT_OK}
    return Cliente(proveedor, ModeloConfig(proveedor=proveedor.id, modelo=modelo),
                   transporte=transporte(respuestas, registro))


def test_lista_los_modelos_del_servidor():
    assert cliente().modelos_disponibles() == ["google/gemma-4-12b", "otro/modelo"]


def test_auto_resuelve_al_modelo_cargado():
    """No hace falta acertar el identificador exacto que le pone LM Studio."""
    assert cliente(modelo="auto").modelo_efectivo() == "google/gemma-4-12b"


def test_auto_solo_pregunta_una_vez():
    registro = []
    c = cliente(modelo="auto", registro=registro)
    c.modelo_efectivo()
    c.modelo_efectivo()
    assert sum(1 for r in registro if r["url"].endswith("/models")) == 1


def test_auto_falla_con_un_mensaje_util_si_no_hay_modelo_cargado():
    c = cliente(modelo="auto", respuestas={"models": {"data": []}, "chat": CHAT_OK})
    with pytest.raises(ErrorLLM, match="ningún modelo cargado"):
        c.modelo_efectivo()


def test_un_modelo_fijo_no_consulta_al_servidor():
    registro = []
    cliente(modelo="qwen2.5:7b", registro=registro).modelo_efectivo()
    assert registro == []


def test_el_esquema_viaja_como_response_format():
    """Es la decodificación restringida: sin esto el modelo local inventa el formato."""
    registro = []
    c = cliente(modelo="m", registro=registro)
    c.completar([{"role": "user", "content": "hola"}], esquema={"type": "object"})

    enviado = registro[0]["cuerpo"]
    assert enviado["response_format"]["type"] == "json_schema"
    assert enviado["response_format"]["json_schema"]["strict"] is True


def test_sin_esquema_no_se_manda_response_format():
    registro = []
    cliente(modelo="m", registro=registro).completar([{"role": "user", "content": "x"}])
    assert "response_format" not in registro[0]["cuerpo"]


def test_devuelve_el_texto_y_el_consumo():
    r = cliente(modelo="m").completar([{"role": "user", "content": "x"}])
    assert r.json_() == {"ok": True}
    assert (r.tokens_entrada, r.tokens_salida) == (12, 5)


def test_tolera_que_el_modelo_envuelva_el_json_en_un_bloque_de_codigo():
    """Los modelos locales lo hacen constantemente."""
    respuestas = {"models": MODELOS_OK,
                  "chat": {"choices": [{"message": {"content": '```json\n{"a": 1}\n```'}}]}}
    assert cliente(modelo="m", respuestas=respuestas).completar([]).json_() == {"a": 1}


def test_una_respuesta_que_no_es_json_falla_con_claridad():
    respuestas = {"models": MODELOS_OK, "chat": {"choices": [{"message": {"content": "hola!"}}]}}
    with pytest.raises(ErrorLLM, match="no es JSON válido"):
        cliente(modelo="m", respuestas=respuestas).completar([]).json_()


def test_sin_opciones_en_la_respuesta_falla():
    respuestas = {"models": MODELOS_OK, "chat": {"choices": []}}
    with pytest.raises(ErrorLLM, match="ninguna respuesta"):
        cliente(modelo="m", respuestas=respuestas).completar([])


def test_la_clave_va_en_la_cabecera_cuando_existe(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-prueba")
    registro = []
    cliente(modelo="m", proveedor=NUBE, registro=registro).completar([])
    assert registro[0]["cabeceras"]["Authorization"] == "Bearer sk-prueba"


def test_sin_clave_no_se_manda_cabecera_de_autorizacion(monkeypatch):
    monkeypatch.delenv("LMSTUDIO_API_KEY", raising=False)
    registro = []
    cliente(modelo="m", registro=registro).completar([])
    assert "Authorization" not in registro[0]["cabeceras"]


def test_un_error_no_reintentable_no_se_reintenta():
    registro = []
    def t(url, cuerpo, cabeceras, limite):
        registro.append(url)
        raise ErrorLLM("400 desde el servidor: petición inválida")
    c = Cliente(LOCAL, ModeloConfig(proveedor="lmstudio", modelo="m"), transporte=t)
    with pytest.raises(ErrorLLM, match="400"):
        c.completar([])
    assert len(registro) == 1


def test_una_respuesta_cortada_se_reporta_como_corte_y_no_como_json_invalido():
    """Sin esto, el error manda a depurar el sitio equivocado."""
    respuestas = {"models": MODELOS_OK, "chat": {
        "choices": [{"message": {"content": '{\\n "capital": "Santi'},
                     "finish_reason": "length"}],
        "usage": {"completion_tokens": 400},
    }}
    r = cliente(modelo="m", respuestas=respuestas).completar([])
    assert r.motivo_fin == "length"
    with pytest.raises(ErrorLLM, match="se cortó por el tope de tokens"):
        r.json_()


def test_un_json_invalido_sin_corte_muestra_lo_que_devolvio():
    respuestas = {"models": MODELOS_OK, "chat": {
        "choices": [{"message": {"content": "no soy JSON"}, "finish_reason": "stop"}]}}
    with pytest.raises(ErrorLLM, match="no soy JSON"):
        cliente(modelo="m", respuestas=respuestas).completar([]).json_()


def test_se_manda_tambien_el_nombre_nuevo_del_tope_de_tokens():
    """Algunos servidores ya solo miran max_completion_tokens."""
    registro = []
    cliente(modelo="m", registro=registro).completar([])
    assert registro[0]["cuerpo"]["max_completion_tokens"] == registro[0]["cuerpo"]["max_tokens"]
