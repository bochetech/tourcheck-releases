"""El importador de punta a punta: de la caché al currículo canónico.

Aquí no hay lógica nueva, solo el orden. Cada pieza ya sabe hacer su parte y este
módulo las encadena y cuenta qué pasó. Deliberadamente **no** llama al bucle de
reparación: importar y reparar son cosas distintas, y el que las junta es el
comando `import`, no este módulo. Así se puede importar y mirar el resultado
crudo antes de dejar que un modelo lo toque.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from pydantic import BaseModel, Field

from aula.config import Config, Rol
from aula.curriculum.model import Curriculum, FuenteCurriculo
from aula.importador.catalogo import Documento, catalogo
from aula.importador.codigos import IndiceCodigos
from aula.importador.contexto import ContextoDocumento, detectar
from aula.importador.consolidar import Consolidacion, construir_curriculum, consolidar
from aula.importador.descarga import CACHE_POR_DEFECTO, Descarga, cargar_manifiesto
from aula.importador.extraccion import (
    ObjetivoExtraido,
    ResultadoExtraccion,
    extraer,
    objetivos_no_vistos,
)
from aula.importador.pases import Informe, enriquecer
from aula.importador.texto import DocumentoTexto, SinCapaDeTexto, leer_texto
from aula.importador.trozos import trocear
from aula.llm.cliente import para_rol


class InformeImportacion(BaseModel):
    """Todo lo que hay que mirar después de una importación. Una sola vez."""

    documentos: list[str] = Field(default_factory=list)
    codigos_en_documentos: int = 0
    objetivos_extraidos: int = 0
    objetivos_finales: int = 0
    descartes: list[str] = Field(default_factory=list)
    no_vistos: list[str] = Field(default_factory=list)
    conflictos: list[str] = Field(default_factory=list)
    dudosos: list[str] = Field(default_factory=list)
    errores: list[str] = Field(default_factory=list)
    informes_pases: list[Informe] = Field(default_factory=list)

    @property
    def cobertura(self) -> float:
        """Qué fracción de los códigos del documento acabó en el currículo.

        Es la métrica honesta del importador, y se calcula sin preguntarle nada al
        modelo: los códigos del denominador salen de una expresión regular.
        """
        if not self.codigos_en_documentos:
            return 0.0
        return self.objetivos_finales / self.codigos_en_documentos

    def resumen(self) -> str:
        return (
            f"{self.objetivos_finales} objetivos de "
            f"{self.codigos_en_documentos} códigos en el documento "
            f"({self.cobertura:.0%} de cobertura)"
        )


def leer_de_cache(
    descarga: Descarga, cache: str | Path = CACHE_POR_DEFECTO
) -> DocumentoTexto:
    """Lee un documento de la caché con la procedencia que dice el manifiesto.

    El título sale del manifiesto y no del nombre del archivo a propósito: es lo
    que acabará en `Fuente.doc` de cada objetivo, y una ruta local ahí sería
    ruido en el YAML y el nombre de una máquina ajena en un repositorio.
    """
    return leer_texto(
        descarga.ruta(Path(cache)),
        doc_id=descarga.id,
        url=descarga.url,
        titulo=descarga.titulo or descarga.id,
    )


def contexto_de(
    doc: DocumentoTexto,
    documento: Documento | None = None,
    *,
    asignatura: str | None = None,
    nivel: str | None = None,
) -> ContextoDocumento:
    """Resuelve asignatura y nivel del documento, por orden de fiabilidad.

    Primero lo que dijo una persona (la línea de comandos), luego lo que declara
    el catálogo, y solo si no hay nada, lo que se deduce de la portada. Hace falta
    para completar los códigos escuetos de un programa de estudio, donde el
    prefijo no está escrito en ninguna línea.
    """
    return detectar(
        doc.texto,
        asignatura=asignatura or (documento.asignatura if documento else None),
        nivel=nivel or (documento.nivel if documento else None),
    )


def extraer_documento(
    descarga: Descarga,
    cliente,
    cache: str | Path = CACHE_POR_DEFECTO,
    al_avanzar=None,
    contexto: ContextoDocumento | None = None,
) -> tuple[DocumentoTexto, IndiceCodigos, ResultadoExtraccion]:
    """Un documento de la caché → objetivos crudos, con procedencia."""
    doc = leer_de_cache(descarga, cache)
    indice = IndiceCodigos(doc, contexto if contexto is not None else contexto_de(doc))
    trozos = trocear(doc, indice)
    resultado = extraer(doc, trozos, cliente, indice, al_avanzar=al_avanzar)
    return doc, indice, resultado


def importar(
    pais: str,
    config: Config,
    *,
    nivel: str | None = None,
    asignatura: str | None = None,
    ids: list[str] | None = None,
    cache: str | Path = CACHE_POR_DEFECTO,
    version: str | None = None,
    con_pases: bool = True,
    transporte=None,
    al_avanzar=None,
) -> tuple[Curriculum, InformeImportacion]:
    """Importa desde la caché. **No toca la red**: lo que no esté, no se importa.

    Es la mitad offline del importador, y la que se puede correr veinte veces
    seguidas mientras se ajusta un prompt. Descargar es trabajo de `fetch`.
    """
    manifiesto = cargar_manifiesto(cache)
    docs_catalogo = {d.id: d for d in catalogo(pais).documentos}

    elegidas: list[Descarga] = []
    informe = InformeImportacion()
    for doc_id, descarga in manifiesto.descargas.items():
        doc = docs_catalogo.get(doc_id)
        if ids is not None and doc_id not in ids:
            continue
        if doc is not None:
            if nivel and doc.nivel and doc.nivel != nivel:
                continue
            if asignatura and doc.asignatura and doc.asignatura != asignatura:
                continue
        elegidas.append(descarga)

    if not elegidas:
        raise FileNotFoundError(
            f"no hay nada en la caché ({cache}) que cuadre con el filtro. "
            "Corre `aula curriculum fetch` primero, o adjunta un documento con "
            "`aula curriculum adjuntar`."
        )

    cliente_extraccion = para_rol(config, Rol.EXTRACCION, transporte=transporte)

    todos: list[ObjetivoExtraido] = []
    codigos_en_fuente: set[str] = set()
    es_temario = False
    nivel_documento = nivel
    licencia = None

    for descarga in elegidas:
        doc_catalogo: Documento | None = docs_catalogo.get(descarga.id)
        try:
            contexto = contexto_de(
                leer_de_cache(descarga, cache),
                doc_catalogo,
                asignatura=asignatura,
                nivel=nivel,
            )
            doc, indice, resultado = extraer_documento(
                descarga, cliente_extraccion, cache, al_avanzar, contexto
            )
        except SinCapaDeTexto as exc:
            informe.errores.append(str(exc))
            continue

        if indice.escuetos_sin_contexto:
            informe.errores.append(
                f"{descarga.id}: {indice.escuetos_sin_contexto} códigos escuetos "
                "sin poder completar. Pasa --asignatura y --nivel."
            )

        informe.documentos.append(descarga.titulo or descarga.id)
        informe.objetivos_extraidos += len(resultado.objetivos)
        informe.errores.extend(resultado.errores)
        informe.descartes.extend(
            f"{d.codigo or '?'} (trozo {d.trozo}): {d.motivo}" for d in resultado.descartes
        )
        informe.no_vistos.extend(objetivos_no_vistos(indice, resultado))

        todos.extend(resultado.objetivos)
        codigos_en_fuente.update(indice.codigos)
        licencia = licencia or descarga.licencia
        if doc_catalogo is not None and doc_catalogo.clase == "temario":
            es_temario = True
        if nivel_documento is None:
            nivel_documento = contexto.nivel

    informe.codigos_en_documentos = len(codigos_en_fuente)

    consolidacion: Consolidacion = consolidar(
        todos, codigos_en_fuente=codigos_en_fuente, nivel_documento=nivel_documento
    )
    informe.conflictos = [c.codigo for c in consolidacion.conflictos]
    informe.descartes.extend(
        f"{cod}: {motivo}" for cod, motivo in consolidacion.descartados.items()
    )

    cat = catalogo(pais)
    curriculo = construir_curriculum(
        consolidacion,
        id_curriculo=f"{pais.lower()}-{cat.organismo.lower()}"
        + (f"-{nivel}" if nivel else ""),
        version=version or _dt.date.today().strftime("%Y-%m"),
        fuente=FuenteCurriculo(pais=pais.upper(), organismo=cat.organismo, url=cat.url),
        licencia=licencia,
        es_temario=es_temario,
    )

    if con_pases:
        curriculo, informes = enriquecer(
            curriculo,
            para_rol(config, Rol.ENRIQUECIMIENTO, transporte=transporte),
            para_rol(config, Rol.RESUMEN, transporte=transporte),
            para_rol(config, Rol.ITEMS, transporte=transporte),
            al_avanzar=al_avanzar,
        )
        informe.informes_pases = informes

    informe.objetivos_finales = len(curriculo.objetivos)
    informe.dudosos = [o.codigo for o in consolidacion.dudosos]
    return curriculo, informe
