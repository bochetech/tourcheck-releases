"""Cliente de modelos de lenguaje, compatible con la API de OpenAI.

Ollama y LM Studio exponen esa misma interfaz, así que pasar de un modelo local a
uno en la nube es cambiar la URL base y la clave. Sin dependencias externas: basta
la biblioteca estándar, y así el proyecto arranca en cualquier máquina.

La pieza importante es `esquema=`: cuando se pasa un esquema JSON, la respuesta se
pide con `response_format` de tipo `json_schema`. Eso es **decodificación
restringida** — el servidor obliga al modelo a producir algo que valida contra el
esquema. Sin esto, un modelo local de 7-12B se inventa el formato con frecuencia,
y todo el vocabulario cerrado de reparación se vendría abajo.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel

from aula.config import Config, ModeloConfig, Proveedor, Rol

TIEMPO_LIMITE = 180.0
REINTENTOS = 2


class ErrorLLM(RuntimeError):
    """Falló la llamada al modelo, con el motivo que devolvió el servidor."""


class RespuestaLLM(BaseModel):
    texto: str
    modelo: str
    tokens_entrada: int = 0
    tokens_salida: int = 0
    motivo_fin: str = ""

    def json_(self) -> Any:
        """Interpreta la respuesta como JSON, tolerando adornos del modelo."""
        texto = self.texto.strip()
        if texto.startswith("```"):
            # Algunos modelos locales envuelven el JSON en un bloque de código.
            texto = texto.split("\n", 1)[-1]
            if texto.rstrip().endswith("```"):
                texto = texto.rstrip()[:-3]
        try:
            return json.loads(texto)
        except json.JSONDecodeError as exc:
            # Sin esto, una respuesta cortada se reporta como "JSON inválido" y
            # manda a depurar el sitio equivocado.
            if self.motivo_fin == "length":
                raise ErrorLLM(
                    f"la respuesta se cortó por el tope de tokens "
                    f"({self.tokens_salida} generados). Sube `max_tokens` del rol."
                ) from exc
            raise ErrorLLM(
                f"la respuesta no es JSON válido: {exc}. "
                f"Devolvió: {self.texto[:200]!r}"
            ) from exc


class Cliente:
    """Habla con un proveedor concreto para un rol concreto."""

    def __init__(self, proveedor: Proveedor, modelo: ModeloConfig, transporte=None):
        self.proveedor = proveedor
        self.modelo = modelo
        self._transporte = transporte or _pedir_http
        self._resuelto: str | None = None

    # -- descubrimiento --------------------------------------------------------

    def modelos_disponibles(self) -> list[str]:
        """Pregunta al servidor qué modelos tiene. LM Studio devuelve el cargado."""
        url = self.proveedor.base_url.rstrip("/") + "/models"
        datos = self._transporte(url, None, self._cabeceras(), TIEMPO_LIMITE)
        return [m.get("id", "") for m in datos.get("data", []) if m.get("id")]

    def modelo_efectivo(self) -> str:
        """Resuelve `auto` preguntándole al servidor cuál tiene cargado."""
        if self.modelo.modelo != "auto":
            return self.modelo.modelo
        if self._resuelto is None:
            disponibles = self.modelos_disponibles()
            if not disponibles:
                raise ErrorLLM(
                    f"'{self.proveedor.id}' no reporta ningún modelo cargado en "
                    f"{self.proveedor.base_url}"
                )
            self._resuelto = disponibles[0]
        return self._resuelto

    # -- generación ------------------------------------------------------------

    def completar(
        self,
        mensajes: list[dict],
        esquema: dict | None = None,
        nombre_esquema: str = "respuesta",
    ) -> RespuestaLLM:
        """Pide una respuesta. Con `esquema`, la fuerza a validar contra él."""
        cuerpo: dict[str, Any] = {
            "model": self.modelo_efectivo(),
            "messages": mensajes,
            "temperature": self.modelo.temperatura,
            "max_tokens": self.modelo.max_tokens,
            # Algunos servidores ya solo miran el nombre nuevo.
            "max_completion_tokens": self.modelo.max_tokens,
        }
        if esquema is not None:
            cuerpo["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": nombre_esquema, "strict": True, "schema": esquema},
            }

        url = self.proveedor.base_url.rstrip("/") + "/chat/completions"
        datos = self._con_reintentos(url, cuerpo)

        opciones = datos.get("choices") or []
        if not opciones:
            raise ErrorLLM("el servidor no devolvió ninguna respuesta")
        uso = datos.get("usage") or {}
        return RespuestaLLM(
            texto=(opciones[0].get("message") or {}).get("content") or "",
            modelo=datos.get("model", cuerpo["model"]),
            tokens_entrada=uso.get("prompt_tokens", 0) or 0,
            tokens_salida=uso.get("completion_tokens", 0) or 0,
            motivo_fin=opciones[0].get("finish_reason") or "",
        )

    # -- interno ---------------------------------------------------------------

    def _cabeceras(self) -> dict[str, str]:
        cabeceras = {"Content-Type": "application/json"}
        clave = self.proveedor.api_key()
        if clave:
            cabeceras["Authorization"] = f"Bearer {clave}"
        return cabeceras

    def _con_reintentos(self, url: str, cuerpo: dict) -> dict:
        ultimo: Exception | None = None
        for intento in range(REINTENTOS + 1):
            try:
                return self._transporte(url, cuerpo, self._cabeceras(), TIEMPO_LIMITE)
            except ErrorLLM as exc:
                ultimo = exc
                if not _vale_la_pena_reintentar(exc):
                    raise
                if intento < REINTENTOS:
                    time.sleep(1.5 * (intento + 1))
        raise ErrorLLM(f"falló tras {REINTENTOS + 1} intentos: {ultimo}")


def _vale_la_pena_reintentar(exc: ErrorLLM) -> bool:
    mensaje = str(exc)
    return any(marca in mensaje for marca in ("429", "500", "502", "503", "504", "tiempo"))


def _pedir_http(url: str, cuerpo: dict | None, cabeceras: dict, limite: float) -> dict:
    """Transporte real. Se inyecta otro en los tests para no salir a la red."""
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    peticion = urllib.request.Request(url, data=datos, headers=cabeceras, method="POST" if datos else "GET")
    try:
        with urllib.request.urlopen(peticion, timeout=limite) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", "replace")[:400]
        raise ErrorLLM(f"{exc.code} desde {url}: {detalle}") from exc
    except urllib.error.URLError as exc:
        raise ErrorLLM(
            f"no se pudo conectar con {url}: {exc.reason}. "
            "¿Está corriendo el servidor local?"
        ) from exc
    except TimeoutError as exc:
        raise ErrorLLM(f"tiempo agotado esperando a {url}") from exc


def para_rol(config: Config, rol: Rol, transporte=None) -> Cliente:
    """Construye el cliente que corresponde a un rol según la configuración."""
    return Cliente(config.proveedor_de(rol), config.para(rol), transporte=transporte)
