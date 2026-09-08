"""Trozo → objetivos. El modelo propone, el índice de códigos dispone.

El reparto de trabajo es deliberado y no negociable:

- **El modelo** aporta lo que una expresión regular no puede: qué texto
  corresponde a cada código, a qué unidad pertenece, de qué asignatura es.
- **El código** aporta todo lo verificable: que el código exista en el documento,
  en qué página estaba, de qué documento y URL viene.

Por eso ningún campo de procedencia se le pregunta al modelo. Puede alucinar un
código; no puede alucinar la página del PDF donde estaba, porque esa la calcula
`DocumentoTexto.procedencia_en` sobre la posición real de la coincidencia.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from aula.curriculum.model import Fuente, TipoObjetivo
from aula.importador.codigos import IndiceCodigos, normalizar
from aula.importador.texto import DocumentoTexto
from aula.importador.trozos import Trozo
from aula.llm.cliente import Cliente, ErrorLLM

INSTRUCCIONES = """Extraes objetivos de aprendizaje de un documento curricular oficial.

Reglas:
- Copia el texto del objetivo LITERAL del documento. No lo resumas ni lo reescribas.
- El código va tal como aparece, con su forma completa (por ejemplo "MA05 OA 01").
- No inventes códigos: si no está escrito en el fragmento, no existe.
- Si el fragmento no contiene ningún objetivo, devuelve la lista vacía y marca
  `sin_objetivos` en true. Es una respuesta correcta y frecuente.
- No añadas objetivos que no estén en el fragmento aunque los conozcas."""


class ObjetivoCrudo(BaseModel):
    codigo: str
    texto: str
    asignatura: str | None = None
    unidad: str | None = None


class Extraccion(BaseModel):
    objetivos: list[ObjetivoCrudo] = Field(default_factory=list)
    # Distingue "miré y no había nada" de "la llamada salió mal". Sin esta marca
    # ambas cosas llegan como una lista vacía y no hay forma de saber si el
    # documento no tenía objetivos o si el importador se quedó ciego.
    sin_objetivos: bool = False


class ObjetivoExtraido(BaseModel):
    """Un objetivo aceptado, ya con la procedencia calculada por el código."""

    codigo: str
    texto: str
    asignatura: str | None = None
    unidad: str | None = None
    tipo: TipoObjetivo = TipoObjetivo.CONOCIMIENTO
    nivel: str | None = None
    fuente: Fuente | None = None
    doc_id: str = ""
    trozo: int = 0


class Descarte(BaseModel):
    """Algo que el modelo devolvió y no se aceptó, con el motivo.

    Los descartes no se tiran: son la medida de cuánto se está inventando el
    modelo, y lo primero que hay que mirar cuando una importación sale rara.
    """

    codigo: str
    motivo: str
    trozo: int = 0


class ResultadoExtraccion(BaseModel):
    objetivos: list[ObjetivoExtraido] = Field(default_factory=list)
    descartes: list[Descarte] = Field(default_factory=list)
    trozos_vistos: int = 0
    trozos_fallidos: int = 0
    errores: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.trozos_vistos > 0 and self.trozos_fallidos < self.trozos_vistos


def esquema_extraccion() -> dict[str, Any]:
    esquema = Extraccion.model_json_schema()
    _cerrar(esquema)
    return esquema


def _cerrar(nodo: Any) -> None:
    """Mismo endurecimiento que usa el reparador, por el mismo motivo.

    Los objetos se cierran porque varios servidores lo exigen en modo estricto, y
    `oneOf` pasa a `anyOf` porque el motor de gramáticas de LM Studio rechaza el
    primero de plano. Lo aprendimos de un fallo real, no de la documentación.
    """
    if isinstance(nodo, dict):
        if nodo.get("type") == "object" and "additionalProperties" not in nodo:
            nodo["additionalProperties"] = False
        if "oneOf" in nodo and "anyOf" not in nodo:
            nodo["anyOf"] = nodo.pop("oneOf")
        nodo.pop("discriminator", None)
        for valor in nodo.values():
            _cerrar(valor)
    elif isinstance(nodo, list):
        for valor in nodo:
            _cerrar(valor)


def extraer_trozo(
    trozo: Trozo,
    cliente: Cliente,
    doc: DocumentoTexto,
    indice: IndiceCodigos,
    numero: int = 0,
) -> tuple[list[ObjetivoExtraido], list[Descarte]]:
    """Una llamada al modelo por trozo, y una criba completa de lo que vuelva."""
    mensajes = [
        {"role": "system", "content": INSTRUCCIONES},
        {"role": "user", "content": trozo.texto},
    ]
    respuesta = cliente.completar(
        mensajes, esquema=esquema_extraccion(), nombre_esquema="extraccion"
    )
    return criba(respuesta.json_(), trozo, doc, indice, numero)


def criba(
    crudo: Any,
    trozo: Trozo,
    doc: DocumentoTexto,
    indice: IndiceCodigos,
    numero: int = 0,
) -> tuple[list[ObjetivoExtraido], list[Descarte]]:
    """Filtra lo que devolvió el modelo y le pega la procedencia real.

    Se interpreta objetivo por objetivo a propósito: que el modelo se equivoque
    en el tercero no debe tirar los dos primeros, que estaban bien.
    """
    aceptados: list[ObjetivoExtraido] = []
    descartes: list[Descarte] = []

    if isinstance(crudo, list):
        crudo = {"objetivos": crudo}
    if not isinstance(crudo, dict):
        return [], [Descarte(codigo="", motivo="la respuesta no tiene la forma esperada",
                             trozo=numero)]

    for entrada in crudo.get("objetivos") or []:
        try:
            bruto = ObjetivoCrudo.model_validate(entrada)
        except ValidationError as exc:
            descartes.append(
                Descarte(
                    codigo=str((entrada or {}).get("codigo", ""))[:40],
                    motivo=f"no valida como objetivo: {_primer_error(exc)}",
                    trozo=numero,
                )
            )
            continue

        canonico = normalizar(bruto.codigo)
        if canonico is None:
            descartes.append(
                Descarte(
                    codigo=bruto.codigo[:40],
                    motivo="el código no tiene la forma de un código de objetivo",
                    trozo=numero,
                )
            )
            continue

        aparicion = indice.primera(canonico)
        if aparicion is None:
            # El caso peligroso: un código con la forma correcta que no está en
            # el documento. Se cae aquí y no en la validación posterior, porque
            # más adelante ya no habría manera de distinguirlo de uno legítimo.
            descartes.append(
                Descarte(
                    codigo=canonico,
                    motivo="el código no aparece en el documento (inventado)",
                    trozo=numero,
                )
            )
            continue

        if not bruto.texto.strip():
            descartes.append(
                Descarte(codigo=canonico, motivo="sin texto", trozo=numero)
            )
            continue

        aceptados.append(
            ObjetivoExtraido(
                codigo=canonico,
                texto=" ".join(bruto.texto.split()),
                asignatura=(bruto.asignatura or aparicion.asignatura or "").strip()
                or None,
                unidad=(bruto.unidad or "").strip() or None,
                tipo=aparicion.tipo,
                nivel=aparicion.nivel,
                fuente=doc.procedencia_en(aparicion.inicio),
                doc_id=doc.doc_id,
                trozo=numero,
            )
        )

    return aceptados, descartes


def _primer_error(exc: ValidationError) -> str:
    errores = exc.errors()
    if not errores:  # pragma: no cover - defensivo
        return "error de validación"
    primero = errores[0]
    campo = ".".join(str(p) for p in primero.get("loc", ())) or "?"
    return f"{campo}: {primero.get('msg', '')}"


def extraer(
    doc: DocumentoTexto,
    trozos: list[Trozo],
    cliente: Cliente,
    indice: IndiceCodigos | None = None,
    al_avanzar=None,
) -> ResultadoExtraccion:
    """Recorre los trozos de un documento y junta todo lo que sobreviva."""
    indice = indice if indice is not None else IndiceCodigos(doc)
    resultado = ResultadoExtraccion(trozos_vistos=len(trozos))

    for numero, trozo in enumerate(trozos, start=1):
        try:
            objetivos, descartes = extraer_trozo(trozo, cliente, doc, indice, numero)
        except ErrorLLM as exc:
            # Un trozo perdido no invalida el documento: se anota y se sigue. Lo
            # que sí invalida es que fallen todos, y para eso está `ok`.
            resultado.trozos_fallidos += 1
            resultado.errores.append(f"trozo {numero}: {exc}")
            objetivos, descartes = [], []
        resultado.objetivos.extend(objetivos)
        resultado.descartes.extend(descartes)
        if al_avanzar is not None:
            al_avanzar("extraccion", numero, len(trozos))

    return resultado


def objetivos_no_vistos(indice: IndiceCodigos, resultado: ResultadoExtraccion) -> list[str]:
    """Códigos que están en el documento y el modelo no devolvió.

    Es la métrica de cobertura, y se calcula sin intervención del modelo. Si esta
    lista es larga, el problema es la extracción, no el documento.
    """
    extraidos = {o.codigo for o in resultado.objetivos}
    return [c for c in indice.codigos if c not in extraidos]


def como_json(resultado: ResultadoExtraccion) -> str:  # pragma: no cover - CLI
    return json.dumps(resultado.model_dump(mode="json"), ensure_ascii=False, indent=2)
