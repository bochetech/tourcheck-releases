"""Trocear el documento para que quepa en el modelo, sin partir ningún objetivo.

El troceo ingenuo —cada N caracteres— parte objetivos por la mitad y pierde
justo lo que hemos venido a buscar. Aquí los cortes caen **solo donde empieza un
código**, que es donde empieza un objetivo. Un objetivo puede quedar solo en un
trozo o repetido en dos, nunca partido en dos mitades inservibles.

El solapamiento es deliberado: el último bloque de cada trozo se repite al
principio del siguiente. Eso produce duplicados a propósito, y un objetivo que
aparece dos veces con el mismo texto es **señal de confianza**, no un problema:
la consolidación lo fusiona y le sube la puntuación.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aula.importador.codigos import CodigoEnDocumento, IndiceCodigos
from aula.importador.texto import DocumentoTexto

#: Presupuesto por trozo, en caracteres. ~2.400 tokens en español, que deja aire
#: para las instrucciones y la respuesta en una ventana de 8k.
MAX_CARACTERES = 8_000

#: Un párrafo suelto más corto que esto no vale una llamada al modelo.
MIN_CARACTERES_UTILES = 80

#: Un bloque que no pasa de esto es el código a secas, sin objetivo detrás:
#: una línea de índice.
LARGO_CODIGO_SUELTO = 24


class Trozo(BaseModel):
    """Un pedazo del documento con todo lo necesario para situarlo de nuevo."""

    doc_id: str
    texto: str
    inicio: int
    fin: int
    pagina_desde: int
    pagina_hasta: int
    #: Códigos que el índice —no el modelo— encontró aquí. Es la lista contra la
    #: que se contrasta lo que devuelva el modelo.
    codigos: list[str] = Field(default_factory=list)

    def __len__(self) -> int:  # pragma: no cover - conveniencia
        return len(self.texto)


def trocear(
    doc: DocumentoTexto,
    indice: IndiceCodigos | None = None,
    *,
    max_caracteres: int = MAX_CARACTERES,
    solape: int = 1,
) -> list[Trozo]:
    """Parte el documento en trozos cortados en fronteras de código.

    Si el documento no tiene ni un código, cae en troceo por párrafos: puede que
    sea un plan de horas o una portada, y no hay razón para devolver nada.
    """
    indice = indice if indice is not None else IndiceCodigos(doc)
    if not indice.apariciones:
        return _por_parrafos(doc, max_caracteres)

    bloques = _bloques(doc, indice.apariciones)
    return _agrupar(doc, bloques, max_caracteres, solape)


def _bloques(
    doc: DocumentoTexto, apariciones: list[CodigoEnDocumento]
) -> list[tuple[int, int, list[str]]]:
    """Un bloque por código: desde donde aparece hasta el código siguiente.

    Lo que hay antes del primer código se emite como bloque propio. Podría no
    contener ningún objetivo —suele ser portada e índice— pero descartarlo por
    suposición es exactamente el tipo de atajo que hace perder contenido.
    """
    bloques: list[tuple[int, int, list[str]]] = []
    primero = apariciones[0].inicio
    if primero > MIN_CARACTERES_UTILES:
        bloques.append((0, primero, []))

    for i, ap in enumerate(apariciones):
        fin = apariciones[i + 1].inicio if i + 1 < len(apariciones) else len(doc.texto)
        if bloques and bloques[-1][2]:
            inicio_prev, fin_prev, codigos_prev = bloques[-1]
            # Un bloque anterior que es solo el código, sin texto detrás, es una
            # línea de índice o de tabla de contenidos. Se acumulan en el mismo
            # bloque en vez de generar un trozo microscópico por cada uno; si no,
            # el índice de un programa de estudio se lleva media docena de
            # llamadas al modelo para no decir nada.
            if (
                fin_prev - inicio_prev <= LARGO_CODIGO_SUELTO
                and fin - inicio_prev <= MAX_CARACTERES // 4
            ):
                bloques[-1] = (inicio_prev, fin, codigos_prev + [ap.codigo])
                continue
        bloques.append((ap.inicio, fin, [ap.codigo]))
    return bloques


def _agrupar(
    doc: DocumentoTexto,
    bloques: list[tuple[int, int, list[str]]],
    max_caracteres: int,
    solape: int,
) -> list[Trozo]:
    trozos: list[Trozo] = []
    grupo: list[tuple[int, int, list[str]]] = []

    def cerrar() -> None:
        if not grupo:
            return
        trozos.append(_trozo(doc, grupo))

    for bloque in bloques:
        largo_grupo = (grupo[-1][1] - grupo[0][0]) if grupo else 0
        if grupo and largo_grupo + (bloque[1] - bloque[0]) > max_caracteres:
            cerrar()
            # El solape arranca el grupo nuevo repitiendo el final del anterior.
            grupo = grupo[-solape:] if solape > 0 else []
        grupo.append(bloque)
    cerrar()
    return trozos


def _trozo(doc: DocumentoTexto, grupo: list[tuple[int, int, list[str]]]) -> Trozo:
    inicio, fin = grupo[0][0], grupo[-1][1]
    codigos: list[str] = []
    for _, _, cods in grupo:
        for cod in cods:
            if cod not in codigos:
                codigos.append(cod)
    return Trozo(
        doc_id=doc.doc_id,
        texto=doc.texto[inicio:fin].strip(),
        inicio=inicio,
        fin=fin,
        pagina_desde=doc.pagina_en(inicio),
        pagina_hasta=doc.pagina_en(max(fin - 1, inicio)),
        codigos=codigos,
    )


def _por_parrafos(doc: DocumentoTexto, max_caracteres: int) -> list[Trozo]:
    """Reserva para documentos sin códigos: cortar entre párrafos."""
    trozos: list[Trozo] = []
    inicio = 0
    texto = doc.texto
    while inicio < len(texto):
        fin = min(inicio + max_caracteres, len(texto))
        if fin < len(texto):
            corte = texto.rfind("\n\n", inicio + max_caracteres // 2, fin)
            if corte != -1:
                fin = corte
        pedazo = texto[inicio:fin].strip()
        if len(pedazo) >= MIN_CARACTERES_UTILES:
            trozos.append(
                Trozo(
                    doc_id=doc.doc_id,
                    texto=pedazo,
                    inicio=inicio,
                    fin=fin,
                    pagina_desde=doc.pagina_en(inicio),
                    pagina_hasta=doc.pagina_en(max(fin - 1, inicio)),
                )
            )
        inicio = fin
    return trozos
