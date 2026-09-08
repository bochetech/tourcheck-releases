"""Un modelo de mentira que se porta como uno de verdad, sin salir a la red.

No devuelve respuestas fijas: **lee el fragmento que se le manda** y contesta en
consecuencia. Eso es lo que hace que el test de punta a punta signifique algo —
si el troceado pierde un objetivo, este modelo no lo puede inventar, y el test
falla como debe.

Cada escenario feo (código alucinado, respuesta rota, modelo caído) tiene su
propio interruptor, porque son los casos que hay que poder provocar a voluntad.
"""

from __future__ import annotations

import json
import re

from aula.config import ModeloConfig, Proveedor
from aula.importador.codigos import PATRON_CODIGO
from aula.llm.cliente import Cliente, ErrorLLM

PROVEEDOR = Proveedor(
    id="falso", base_url="http://127.0.0.1:1234/v1", apto_para_menores=True
)


class ModeloDeMentira:
    """Transporte falso que entiende de qué va cada llamada por su instrucción."""

    def __init__(
        self,
        *,
        codigos_inventados: list[str] | None = None,
        falla_en_trozo: int | None = None,
        sin_prerrequisitos: bool = False,
        sin_items: bool = False,
        json_roto: bool = False,
    ):
        self.codigos_inventados = codigos_inventados or []
        self.falla_en_trozo = falla_en_trozo
        self.sin_prerrequisitos = sin_prerrequisitos
        self.sin_items = sin_items
        self.json_roto = json_roto
        self.llamadas: list[dict] = []

    # -- transporte -----------------------------------------------------------

    def __call__(self, url, cuerpo, cabeceras, limite):
        if url.endswith("/models"):
            return {"data": [{"id": "modelo-de-mentira"}]}
        self.llamadas.append(cuerpo)
        sistema = cuerpo["messages"][0]["content"]
        usuario = cuerpo["messages"][1]["content"]

        if self.falla_en_trozo is not None and len(self.llamadas) == self.falla_en_trozo:
            raise ErrorLLM("400 el servidor rechazó la petición")
        if self.json_roto:
            return self._responder('{"objetivos": [')

        if "Extraes objetivos" in sistema:
            contenido = self._extraer(usuario)
        elif "Ordenas objetivos" in sistema:
            contenido = self._prerrequisitos(usuario)
        elif "resumen con el que se busca" in sistema:
            contenido = self._resumenes(usuario)
        elif "preguntas para comprobar" in sistema:
            contenido = self._items(usuario)
        else:  # pragma: no cover - defensivo
            contenido = "{}"
        return self._responder(contenido)

    def _responder(self, contenido: str) -> dict:
        return {
            "model": "modelo-de-mentira",
            "choices": [{"message": {"content": contenido}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }

    # -- comportamiento por rol -----------------------------------------------

    def _extraer(self, texto: str) -> str:
        """Devuelve los códigos del fragmento con el texto que los sigue."""
        objetivos = []
        coincidencias = list(PATRON_CODIGO.finditer(texto))
        for i, m in enumerate(coincidencias):
            fin = coincidencias[i + 1].start() if i + 1 < len(coincidencias) else len(texto)
            cuerpo = " ".join(texto[m.end():fin].split())[:300].strip(" .") + "."
            objetivos.append({"codigo": m.group(0), "texto": cuerpo, "asignatura": m.group(1)})
        for inventado in self.codigos_inventados:
            objetivos.append(
                {"codigo": inventado, "texto": "Un objetivo que nadie escribió jamás."}
            )
        return json.dumps(
            {"objetivos": objetivos, "sin_objetivos": not objetivos}, ensure_ascii=False
        )

    def _prerrequisitos(self, texto: str) -> str:
        """Encadena cada objetivo con el anterior de la lista."""
        if self.sin_prerrequisitos:
            return json.dumps({"aristas": []})
        codigos = _codigos_listados(texto)
        aristas = [
            {"objetivo": b, "requiere": a} for a, b in zip(codigos, codigos[1:])
        ]
        return json.dumps({"aristas": aristas})

    def _resumenes(self, texto: str) -> str:
        return json.dumps(
            {
                "resumenes": [
                    {"codigo": c, "resumen": f"Resumen denso del objetivo {c}."}
                    for c in _codigos_listados(texto)
                ]
            },
            ensure_ascii=False,
        )

    def _items(self, texto: str) -> str:
        if self.sin_items:
            return json.dumps({"items": []})
        return json.dumps(
            {
                "items": [
                    {"codigo": c, "items": [f"Pregunta 1 de {c}", f"Pregunta 2 de {c}"]}
                    for c in _codigos_listados(texto)
                ]
            },
            ensure_ascii=False,
        )


_LISTADO = re.compile(r"^([A-ZÑ]{2}\d{2} OAA? (?:\d{2}|[A-Z])):", re.MULTILINE)


def _codigos_listados(texto: str) -> list[str]:
    """Los códigos tal como los manda un pase global: `CODIGO: texto` por línea."""
    return _LISTADO.findall(texto)


def cliente_falso(modelo: ModeloDeMentira, max_tokens: int = 2048) -> Cliente:
    return Cliente(
        PROVEEDOR,
        ModeloConfig(proveedor="falso", modelo="modelo-de-mentira", max_tokens=max_tokens),
        transporte=modelo,
    )
