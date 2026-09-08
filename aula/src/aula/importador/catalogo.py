"""Qué documentos oficiales existen, por país. **Datos, no código.**

Añadir Perú o Colombia debe ser añadir entradas a este archivo, no tocar el
extractor. Por eso el catálogo describe documentos —qué son, dónde están, bajo
qué licencia— y ninguna otra parte del importador sabe nada de Chile.

Cada documento lleva su licencia pegada porque `curriculumnacional.cl` no tiene
una sola: conviven recursos CC BY-SA con otros de derechos reservados. El
importador distribuye código, nunca contenido (`datos/` está en `.gitignore`),
y la licencia viaja hasta el objetivo para que la regla 10 pueda mirarla.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from aula.curriculum.model import Licencia

#: Clases de documento, de la más curada a la más extensa.
#:
#: - `temario`: el temario del examen libre. Corto, ya curado, y **es el blanco
#:   oficial** del sistema. Por eso es lo primero que se importa.
#: - `programa`: Programa de Estudio de una asignatura y nivel. Largo (~200 pp.)
#:   pero es donde están los OA con su texto completo, unidades y horas.
#: - `bases`: Bases Curriculares. La norma de la que cuelga todo lo demás.
#: - `plan_horas`: Plan de Estudio, las horas anuales por asignatura.
Clase = Literal["temario", "programa", "bases", "plan_horas", "oa"]

#: Licencia por defecto de lo que publica el MINEDUC: se puede consultar y usar,
#: pero no se asume permiso de redistribución mientras no diga lo contrario. Es
#: el supuesto conservador, y el que hace que la regla 10 avise en vez de callar.
MINEDUC_RESERVADO = Licencia(
    tipo="MINEDUC — derechos reservados salvo indicación expresa",
    url="https://www.curriculumnacional.cl/",
    puede_redistribuir=False,
)


class Documento(BaseModel):
    """Un documento oficial: qué es, dónde está y qué se puede hacer con él."""

    id: str
    tipo: Literal["pdf", "html"]
    clase: Clase
    titulo: str = ""
    #: `None` significa que no se conoce una URL estable y solo se puede adjuntar
    #: desde un archivo local (`aula curriculum adjuntar`).
    url: str | None = None
    nivel: str | None = None
    asignatura: str | None = None
    licencia: Licencia = MINEDUC_RESERVADO
    #: Los inactivos se declaran pero no se descargan por defecto: o son enormes,
    #: o su URL no está verificada. Se activan con `--incluir-inactivos`.
    activo: bool = True
    #: Por qué está inactivo, o cualquier cosa que quien lo use deba saber.
    notas: str = ""

    def nombre_archivo(self) -> str:
        return f"{self.id}.{self.tipo}"


class Catalogo(BaseModel):
    pais: str
    organismo: str
    url: str | None = None
    documentos: list[Documento] = Field(default_factory=list)


CHILE = Catalogo(
    pais="CL",
    organismo="MINEDUC-UCE",
    url="https://www.curriculumnacional.cl/",
    documentos=[
        # -- Temarios de examen libre: el blanco oficial y el primer arranque ----
        Documento(
            id="cl-temario-02-basico",
            tipo="pdf",
            clase="temario",
            titulo="Temario examen libre — 2º básico",
            url=(
                "https://www.ayudamineduc.cl/sites/default/files/"
                "temario_basica_2deg_basico_uce_0.pdf"
            ),
            nivel="02",
        ),
        Documento(
            id="cl-temario-07-basico",
            tipo="pdf",
            clase="temario",
            titulo="Temario examen libre — 7º básico",
            url=None,
            nivel="07",
            activo=False,
            notas=(
                "La URL del temario de 7º no está verificada. Bájalo desde "
                "ayudamineduc.cl y adjúntalo con `aula curriculum adjuntar`."
            ),
        ),
        # -- Programas de estudio: el texto completo de cada OA -----------------
        #
        # `curriculumnacional.cl` los sirve como `articles-NNNNN_programa.pdf`, con
        # un número distinto por asignatura y nivel. No se declaran URLs a ciegas:
        # se adjunta el archivo que ya se tenga y el importador lo trata igual.
        Documento(
            id="cl-programa-matematica",
            tipo="pdf",
            clase="programa",
            titulo="Programa de Estudio — Matemática",
            url=None,
            asignatura="MA",
            activo=False,
            notas=(
                "Adjuntar el PDF descargado de curriculumnacional.cl "
                "(articles-NNNNN_programa.pdf) con `aula curriculum adjuntar`."
            ),
        ),
        Documento(
            id="cl-programa-lenguaje",
            tipo="pdf",
            clase="programa",
            titulo="Programa de Estudio — Lenguaje y Comunicación",
            url=None,
            asignatura="LE",
            activo=False,
            notas="Adjuntar el PDF descargado de curriculumnacional.cl.",
        ),
    ],
)


CATALOGOS: dict[str, Catalogo] = {"CL": CHILE}


def catalogo(pais: str) -> Catalogo:
    """Devuelve el catálogo de un país, o dice cuáles hay."""
    clave = pais.upper()
    if clave not in CATALOGOS:
        disponibles = ", ".join(sorted(CATALOGOS)) or "ninguno"
        raise KeyError(f"no hay catálogo para '{pais}'. Disponibles: {disponibles}")
    return CATALOGOS[clave]


def documentos(
    pais: str,
    *,
    nivel: str | None = None,
    asignatura: str | None = None,
    clase: Clase | None = None,
    ids: list[str] | None = None,
    incluir_inactivos: bool = False,
) -> list[Documento]:
    """Filtra el catálogo. Sin filtros, devuelve los documentos activos del país."""
    encontrados = []
    for doc in catalogo(pais).documentos:
        if ids is not None:
            if doc.id not in ids:
                continue
        elif not doc.activo and not incluir_inactivos:
            continue
        if nivel is not None and doc.nivel is not None and doc.nivel != nivel:
            continue
        if (
            asignatura is not None
            and doc.asignatura is not None
            and doc.asignatura != asignatura
        ):
            continue
        if clase is not None and doc.clase != clase:
            continue
        encontrados.append(doc)
    return encontrados


def por_id(pais: str, doc_id: str) -> Documento:
    for doc in catalogo(pais).documentos:
        if doc.id == doc_id:
            return doc
    conocidos = ", ".join(d.id for d in catalogo(pais).documentos)
    raise KeyError(f"'{doc_id}' no está en el catálogo de {pais}. Hay: {conocidos}")
