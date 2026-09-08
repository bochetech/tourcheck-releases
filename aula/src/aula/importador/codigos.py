"""Índice de códigos de objetivo, sacado del documento **antes** de tocar el modelo.

Esta es la decisión que sostiene la confianza en todo el importador: los códigos
no se le preguntan a la IA, se buscan en el documento con una expresión regular.
El modelo solo aporta lo que una expresión regular no puede dar —qué texto
corresponde a cada código, a qué unidad pertenece— y hasta eso se contrasta
después contra este índice.

La consecuencia práctica: un código que el modelo devuelva y que no esté aquí es
una alucinación, y se descarta con motivo. Un código bien formado pero inventado
es más peligroso que uno mal formado, porque el mal formado se cae solo y el otro
se cuela con toda la apariencia de ser correcto. Por eso "aparece en la fuente"
pesa más que "tiene la forma correcta".

El patrón está verificado sobre las dos formas reales del currículo chileno:

    MA05 OA 01     objetivo de aprendizaje, ordinal numérico
    MA05 OAA B     objetivo de aprendizaje actitudinal, ordinal por letra
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from aula.curriculum.model import Fuente, TipoObjetivo
from aula.importador.texto import DocumentoTexto

#: Asignatura (2 letras) + nivel (2 dígitos), la palabra OA u OAA, y el ordinal.
#: `OAA` va primero en la alternancia para que gane sobre `OA`.
#: `\s+` porque en un PDF el espacio puede haberse convertido en salto de línea.
PATRON_CODIGO = re.compile(
    r"\b([A-ZÑ]{2})(\d{2})\s+(OAA|OA)\s+(\d{1,2}|[A-Za-zÑñ])\b"
)


class CodigoEnDocumento(BaseModel):
    """Una aparición de un código en el documento, con su posición exacta."""

    codigo: str
    asignatura: str
    nivel: str
    tipo: TipoObjetivo
    inicio: int
    fin: int
    pagina: int

    def fuente(self, doc: DocumentoTexto) -> Fuente:
        return doc.procedencia_en(self.inicio)


def normalizar(codigo: str) -> str | None:
    """Lleva un código a su forma canónica, o devuelve `None` si no lo es.

    `ma05 oa 1` y `MA05  OA  01` son el mismo objetivo. Sin normalizar, la
    consolidación los trataría como dos y la regla 8 los cantaría como duplicados.
    """
    m = PATRON_CODIGO.search((codigo or "").strip().upper())
    if not m:
        return None
    return _canonico(m)


def _canonico(m: re.Match) -> str:
    asignatura, nivel, palabra, ordinal = m.groups()
    ordinal = ordinal.upper()
    if ordinal.isdigit():
        ordinal = f"{int(ordinal):02d}"
    return f"{asignatura.upper()}{nivel} {palabra.upper()} {ordinal}"


def indexar_codigos(doc: DocumentoTexto) -> list[CodigoEnDocumento]:
    """Encuentra todos los códigos del documento, en orden de aparición.

    Se corre sobre el texto **completo**, antes de trocear. Ese orden importa:
    el troceado usa estas posiciones para cortar solo entre objetivos, y así
    ninguno queda partido por la mitad.
    """
    encontrados: list[CodigoEnDocumento] = []
    for m in PATRON_CODIGO.finditer(doc.texto):
        asignatura, nivel, palabra, _ = m.groups()
        encontrados.append(
            CodigoEnDocumento(
                codigo=_canonico(m),
                asignatura=asignatura.upper(),
                nivel=nivel,
                tipo=(
                    TipoObjetivo.ACTITUD
                    if palabra.upper() == "OAA"
                    else TipoObjetivo.CONOCIMIENTO
                ),
                inicio=m.start(),
                fin=m.end(),
                pagina=doc.pagina_en(m.start()),
            )
        )
    return encontrados


class IndiceCodigos:
    """Consulta rápida sobre los códigos de un documento."""

    def __init__(self, doc: DocumentoTexto):
        self.doc = doc
        self.apariciones = indexar_codigos(doc)
        self._por_codigo: dict[str, list[CodigoEnDocumento]] = {}
        for ap in self.apariciones:
            self._por_codigo.setdefault(ap.codigo, []).append(ap)

    def __contains__(self, codigo: str) -> bool:
        return (normalizar(codigo) or "") in self._por_codigo

    def __len__(self) -> int:
        return len(self._por_codigo)

    @property
    def codigos(self) -> list[str]:
        """Códigos distintos, en orden de primera aparición."""
        return list(self._por_codigo)

    def primera(self, codigo: str) -> CodigoEnDocumento | None:
        apariciones = self._por_codigo.get(normalizar(codigo) or "")
        return apariciones[0] if apariciones else None

    def fuente_de(self, codigo: str) -> Fuente | None:
        """Procedencia calculada del documento, nunca preguntada al modelo."""
        aparicion = self.primera(codigo)
        return self.doc.procedencia_en(aparicion.inicio) if aparicion else None

    def en_rango(self, inicio: int, fin: int) -> list[CodigoEnDocumento]:
        return [ap for ap in self.apariciones if inicio <= ap.inicio < fin]

    def niveles(self) -> set[str]:
        return {ap.nivel for ap in self.apariciones}

    def asignaturas(self) -> set[str]:
        return {ap.asignatura for ap in self.apariciones}
