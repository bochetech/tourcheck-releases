"""Documento → texto plano, **sin perder de qué página salió cada carácter**.

La procedencia no es un adorno: la regla 5 exige `fuente.doc`, y la página es lo
que hace auditable todo lo demás. Sin ella nadie puede comprobar si la IA extrajo
un objetivo o se lo inventó, y un plan de estudios que no se puede auditar no se
le puede poner delante a un niño.

De ahí la pieza central de este módulo: `DocumentoTexto.procedencia_en(offset)`.
El documento se guarda como **un solo texto** con la tabla de dónde empieza cada
página. Cualquier trozo, código o coincidencia se localiza por su posición y la
página sale de la tabla. Así la procedencia se *calcula*, nunca se le pregunta al
modelo.
"""

from __future__ import annotations

import bisect
import html
import re
from html.parser import HTMLParser
from pathlib import Path

from pydantic import BaseModel, Field

from aula.curriculum.model import Fuente

#: Por debajo de esto un PDF de varias páginas es, casi seguro, un escaneo sin
#: capa de texto. Preferimos decirlo a devolver un currículo vacío en silencio.
MIN_CARACTERES_POR_PAGINA = 40

#: Separador entre páginas. Ocupa lugar en los offsets a propósito: así el mapa
#: de páginas es exacto y no hay que corregir nada al buscar.
SALTO_DE_PAGINA = "\n\n"


class SinCapaDeTexto(RuntimeError):
    """El PDF no trae texto extraíble. Casi siempre es un escaneo.

    OCR está fuera de alcance por decisión explícita: añade una dependencia
    pesada y una fuente de error nueva para un caso que se resuelve buscando otra
    edición del documento.
    """


class Pagina(BaseModel):
    numero: int
    texto: str
    #: Dónde empieza esta página dentro del texto completo del documento.
    offset: int


class DocumentoTexto(BaseModel):
    """Un documento leído: el texto entero más el mapa de páginas."""

    doc_id: str
    texto: str
    paginas: list[Pagina] = Field(default_factory=list)
    url: str | None = None
    #: Etiqueta legible que va a `Fuente.doc`. Es lo que verá quien audite el
    #: currículo en YAML, así que nunca es una ruta local: esas no significan
    #: nada fuera de la máquina donde se corrió el importador.
    titulo: str = ""

    def pagina_en(self, offset: int) -> int:
        """Número de página que contiene ese offset del texto completo."""
        if not self.paginas:
            return 1
        inicios = [p.offset for p in self.paginas]
        indice = bisect.bisect_right(inicios, max(offset, 0)) - 1
        return self.paginas[max(indice, 0)].numero

    def procedencia_en(self, offset: int) -> Fuente:
        """La bisagra del módulo: de una posición en el texto a una `Fuente`."""
        return Fuente(
            doc=self.titulo or self.doc_id,
            pagina=self.pagina_en(offset),
            url=self.url,
        )

    def resumen(self) -> str:  # pragma: no cover - conveniencia de CLI
        return (
            f"{self.titulo or self.doc_id}: {len(self.paginas)} páginas, "
            f"{len(self.texto):,} caracteres"
        )


# ---------------------------------------------------------------------------
# Ensamblado
# ---------------------------------------------------------------------------


def desde_paginas(
    doc_id: str,
    textos: list[str],
    *,
    url: str | None = None,
    titulo: str = "",
) -> DocumentoTexto:
    """Une textos de página en un `DocumentoTexto` con el mapa de offsets.

    Es la única función que construye el mapa, así que es la única que puede
    equivocarse en él. Los lectores de PDF y HTML solo producen la lista.
    """
    paginas: list[Pagina] = []
    partes: list[str] = []
    offset = 0
    for numero, texto in enumerate(textos, start=1):
        limpio = _normalizar_espacios(texto)
        paginas.append(Pagina(numero=numero, texto=limpio, offset=offset))
        partes.append(limpio)
        offset += len(limpio) + len(SALTO_DE_PAGINA)
    return DocumentoTexto(
        doc_id=doc_id,
        texto=SALTO_DE_PAGINA.join(partes),
        paginas=paginas,
        url=url,
        titulo=titulo or doc_id,
    )


_ESPACIOS = re.compile(r"[ \t\xa0  ]+")
_LINEAS_VACIAS = re.compile(r"\n{3,}")


def _normalizar_espacios(texto: str) -> str:
    """Colapsa espacios sin tocar los saltos de línea.

    Los saltos importan: en los documentos del MINEDUC cada OA empieza en línea
    propia, y esa estructura es lo que hace fiable el índice de códigos.
    """
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = _ESPACIOS.sub(" ", texto)
    texto = "\n".join(linea.strip() for linea in texto.split("\n"))
    return _LINEAS_VACIAS.sub("\n\n", texto).strip()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def texto_de_pdf(ruta: str | Path, doc_id: str = "", **extra) -> DocumentoTexto:
    """Extrae el texto de un PDF, página por página.

    Usa `pdfminer.six`: hace análisis de disposición, que es lo que hace falta
    para que un programa de estudio a dos columnas no salga con las columnas
    intercaladas. Es dependencia opcional (`pip install 'aula[importador]'`)
    porque el motor de tutoría no la necesita para nada.
    """
    ruta = Path(ruta)
    try:
        from pdfminer.high_level import extract_text
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise ImportError(
            "leer PDF necesita pdfminer.six. Instálalo con: "
            "pip install 'aula[importador]'"
        ) from exc

    # Una sola pasada por el documento. pdfminer separa las páginas con un salto
    # de página (\f), así que partir por ahí sale gratis; pedirlas de una en una
    # vuelve a parsear el PDF entero cada vez y en un programa de 200 páginas eso
    # es la diferencia entre segundos y minutos.
    completo = extract_text(str(ruta)) or ""
    # pdfminer pone un salto de página DESPUÉS de cada página, así que partir deja
    # un elemento vacío al final. Se quita ese y solo ese: descartar todos los
    # vacíos convertiría un PDF escaneado en un documento de cero páginas, y
    # entonces la comprobación de más abajo no llegaría a dispararse.
    textos = completo.split("\f")
    if textos and not textos[-1].strip():
        textos.pop()

    total = len(textos)
    utiles = sum(len(t.strip()) for t in textos)
    if total and utiles < MIN_CARACTERES_POR_PAGINA * total:
        raise SinCapaDeTexto(
            f"{ruta.name}: {total} páginas y solo {utiles} caracteres de texto. "
            "Parece un PDF escaneado, sin capa de texto. Busca otra edición del "
            "documento: el importador no hace OCR."
        )

    return desde_paginas(doc_id or ruta.stem, textos, **extra)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_BLOQUE = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "table", "ul", "ol", "td", "th", "header", "footer",
}
_IGNORADO = {"script", "style", "noscript", "svg", "head"}


class _ATexto(HTMLParser):
    """HTML → texto con la stdlib.

    Como el destino es texto plano, no hace falta `beautifulsoup4` ni `lxml`.
    El repo evita dependencias por principio: cada una es algo que puede romperse
    en la máquina de otra persona.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self._saltando = 0

    def handle_starttag(self, tag, attrs):
        if tag in _IGNORADO:
            self._saltando += 1
        elif tag in _BLOQUE:
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in _IGNORADO and self._saltando:
            self._saltando -= 1
        elif tag in _BLOQUE:
            self.partes.append("\n")

    def handle_data(self, data):
        if not self._saltando:
            self.partes.append(data)

    def texto(self) -> str:
        return html.unescape("".join(self.partes))


def texto_de_html(ruta: str | Path, doc_id: str = "", **extra) -> DocumentoTexto:
    """Una página HTML es un documento de una sola 'página'; la URL es su procedencia."""
    ruta = Path(ruta)
    crudo = ruta.read_bytes().decode("utf-8", "replace")
    parser = _ATexto()
    parser.feed(crudo)
    return desde_paginas(doc_id or ruta.stem, [parser.texto()], **extra)


def leer_texto(ruta: str | Path, doc_id: str = "", **extra) -> DocumentoTexto:
    """Lee un documento eligiendo el lector por la extensión."""
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".pdf":
        return texto_de_pdf(ruta, doc_id, **extra)
    if ruta.suffix.lower() in {".html", ".htm"}:
        return texto_de_html(ruta, doc_id, **extra)
    return desde_paginas(
        doc_id or ruta.stem, [ruta.read_text(encoding="utf-8", errors="replace")], **extra
    )
