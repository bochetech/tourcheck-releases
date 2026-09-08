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

**Los códigos aparecen de dos maneras, y hubo que aprenderlo a golpes.** Un
Programa de Estudio de 206 páginas devolvió cero códigos con el patrón completo,
porque dentro de un programa los objetivos se escriben `OA 1` a secas: el
documento entero es de una asignatura y un nivel, y repetir el prefijo doscientas
veces sería ruido. El prefijo no está escrito, está en la portada.

    MA05 OA 01     forma completa: temarios, bases, listados web
    MA05 OAA B     forma completa, actitudinal (ordinal por letra)
    OA 1           forma escueta: dentro de un programa de estudio
    OAA b          forma escueta, actitudinal
    MA1M OA 01     enseñanza media, donde el nivel es "1M".."4M"

La forma escueta solo se indexa si se sabe de qué asignatura y nivel es el
documento (`contexto.py`). Sin eso no se puede canonicalizar, y meter `OA 1`
suelto en un currículo que mezcla niveles sería peor que no meter nada.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from aula.curriculum.model import Fuente, TipoObjetivo
from aula.importador.contexto import ContextoDocumento
from aula.importador.texto import DocumentoTexto

#: Prefijo opcional (asignatura + nivel), la palabra OA u OAA, y el ordinal.
#: Que el prefijo sea opcional es lo que permite una sola pasada para las dos
#: formas. `OAA` va primero en la alternancia para que gane sobre `OA`, y `\s+`
#: porque al pasar un PDF a texto el espacio puede haberse vuelto un salto.
PATRON_CODIGO = re.compile(
    r"\b(?:([A-ZÑ]{2})(\d{2}|\dM)\s+)?(OAA|OA)\s*(\d{1,2}|[A-Za-zÑñ])\b"
)


def _ordinal_valido(palabra: str, ordinal: str) -> bool:
    """En el currículo chileno los OA van por número y los OAA por letra.

    Exigirlo quita casi todos los falsos positivos de la forma escueta: dentro de
    un texto corrido, `OA` seguido de una palabra suelta deja de colar.
    """
    return ordinal.isdigit() if palabra == "OA" else ordinal.isalpha()


class CodigoEnDocumento(BaseModel):
    """Una aparición de un código en el documento, con su posición exacta."""

    codigo: str
    asignatura: str
    nivel: str
    tipo: TipoObjetivo
    inicio: int
    fin: int
    pagina: int
    #: Si venía escrito entero o se completó con el contexto del documento.
    escueto: bool = False

    def fuente(self, doc: DocumentoTexto) -> Fuente:
        return doc.procedencia_en(self.inicio)


def _canonico(asignatura: str, nivel: str, palabra: str, ordinal: str) -> str:
    ordinal = ordinal.upper()
    if ordinal.isdigit():
        ordinal = f"{int(ordinal):02d}"
    return f"{asignatura.upper()}{nivel.upper()} {palabra.upper()} {ordinal}"


def normalizar(codigo: str, contexto: ContextoDocumento | None = None) -> str | None:
    """Lleva un código a su forma canónica, o devuelve `None` si no lo es.

    `ma05 oa 1` y `MA05  OA  01` son el mismo objetivo. Sin normalizar, la
    consolidación los trataría como dos y la regla 8 los cantaría como duplicados.
    Un código escueto se completa con el contexto; sin contexto, no es un código.
    """
    m = PATRON_CODIGO.search((codigo or "").strip().upper())
    if not m:
        return None
    asignatura, nivel, palabra, ordinal = m.groups()
    if not _ordinal_valido(palabra.upper(), ordinal):
        return None
    if asignatura is None:
        if contexto is None or not contexto.completo:
            return None
        asignatura, nivel = contexto.asignatura, contexto.nivel
    return _canonico(asignatura, nivel, palabra, ordinal)


class ResultadoIndexado(BaseModel):
    apariciones: list[CodigoEnDocumento] = []
    #: Cuántas veces se vio la forma escueta sin poder completarla. Es lo que hace
    #: que el diagnóstico diga "hay 340 códigos, dime de qué nivel" en vez del
    #: inútil "no encontré nada".
    escuetos_sin_contexto: int = 0


def indexar_codigos(
    doc: DocumentoTexto, contexto: ContextoDocumento | None = None
) -> ResultadoIndexado:
    """Encuentra todos los códigos del documento, en orden de aparición.

    Se corre sobre el texto **completo**, antes de trocear. Ese orden importa:
    el troceado usa estas posiciones para cortar solo entre objetivos, y así
    ninguno queda partido por la mitad.
    """
    resultado = ResultadoIndexado()
    for m in PATRON_CODIGO.finditer(doc.texto):
        asignatura, nivel, palabra, ordinal = m.groups()
        palabra = palabra.upper()
        if not _ordinal_valido(palabra, ordinal):
            continue

        escueto = asignatura is None
        if escueto:
            if contexto is None or not contexto.completo:
                resultado.escuetos_sin_contexto += 1
                continue
            asignatura, nivel = contexto.asignatura, contexto.nivel

        resultado.apariciones.append(
            CodigoEnDocumento(
                codigo=_canonico(asignatura, nivel, palabra, ordinal),
                asignatura=asignatura.upper(),
                nivel=nivel.upper(),
                tipo=(
                    TipoObjetivo.ACTITUD if palabra == "OAA"
                    else TipoObjetivo.CONOCIMIENTO
                ),
                inicio=m.start(),
                fin=m.end(),
                pagina=doc.pagina_en(m.start()),
                escueto=escueto,
            )
        )
    return resultado


class IndiceCodigos:
    """Consulta rápida sobre los códigos de un documento."""

    def __init__(self, doc: DocumentoTexto, contexto: ContextoDocumento | None = None):
        self.doc = doc
        self.contexto = contexto
        resultado = indexar_codigos(doc, contexto)
        self.apariciones = resultado.apariciones
        self.escuetos_sin_contexto = resultado.escuetos_sin_contexto
        self._por_codigo: dict[str, list[CodigoEnDocumento]] = {}
        for ap in self.apariciones:
            self._por_codigo.setdefault(ap.codigo, []).append(ap)

    def __contains__(self, codigo: str) -> bool:
        return (normalizar(codigo, self.contexto) or "") in self._por_codigo

    def __len__(self) -> int:
        return len(self._por_codigo)

    @property
    def codigos(self) -> list[str]:
        """Códigos distintos, en orden de primera aparición."""
        return list(self._por_codigo)

    def primera(self, codigo: str) -> CodigoEnDocumento | None:
        apariciones = self._por_codigo.get(normalizar(codigo, self.contexto) or "")
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
