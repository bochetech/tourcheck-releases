"""Caché de documentos en disco: portátil, auditable y con buenos modales.

La caché **es el fixture**. Quien tiene acceso a la red del ministerio corre
`fetch` una vez; quien desarrolla la extracción recibe la carpeta y trabaja
offline contra los documentos reales. Para que eso funcione, la carpeta tiene que
explicarse sola: de ahí el manifiesto con la URL, el sha256 y la licencia de cada
archivo. Una carpeta de PDF sin manifiesto no es una caché, es un montón de PDF.

`datos/` está en `.gitignore` a propósito: se distribuye el importador, nunca el
contenido. Cada archivo lleva su licencia pegada, que es lo que la regla 10
acabará mirando.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from aula.curriculum.model import Licencia
from aula.importador.catalogo import Documento

CACHE_POR_DEFECTO = Path("datos/fuentes")
ARCHIVO_MANIFIESTO = "manifiesto.json"

#: Se identifica el proyecto. Un agente anónimo martillando un sitio público del
#: Estado es exactamente lo que no queremos ser.
AGENTE = "aula/0.1 (importador de currículo; uso educativo personal)"

#: Pausa entre peticiones al mismo servidor. Se descarga cada documento una sola
#: vez en toda la vida del proyecto, así que un segundo no le cuesta nada a nadie.
PAUSA = 1.0

TIEMPO_LIMITE = 120.0


class ErrorDescarga(RuntimeError):
    """No se pudo traer el documento, con el motivo tal cual."""


class Descarga(BaseModel):
    """Una entrada del manifiesto: qué archivo es y de dónde salió."""

    id: str
    archivo: str
    sha256: str
    bytes: int
    url: str | None = None
    content_type: str = ""
    descargado_en: _dt.datetime
    origen: Literal["red", "archivo"] = "red"
    licencia: Licencia = Field(default_factory=Licencia)
    #: Etiqueta legible que acaba en `Fuente.doc` del objetivo. Nunca una ruta
    #: local: en un YAML versionado, `/Users/carlos/Downloads/...` no le dice
    #: nada a nadie y encima filtra el nombre de la máquina.
    titulo: str = ""

    def ruta(self, cache: Path) -> Path:
        return Path(cache) / self.archivo


class Manifiesto(BaseModel):
    version: int = 1
    descargas: dict[str, Descarga] = Field(default_factory=dict)

    def __contains__(self, doc_id: str) -> bool:
        return doc_id in self.descargas

    def get(self, doc_id: str) -> Descarga | None:
        return self.descargas.get(doc_id)


def cargar_manifiesto(cache: str | Path = CACHE_POR_DEFECTO) -> Manifiesto:
    ruta = Path(cache) / ARCHIVO_MANIFIESTO
    if not ruta.exists():
        return Manifiesto()
    return Manifiesto.model_validate_json(ruta.read_text(encoding="utf-8"))


def guardar_manifiesto(manifiesto: Manifiesto, cache: str | Path = CACHE_POR_DEFECTO) -> Path:
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    ruta = cache / ARCHIVO_MANIFIESTO
    ruta.write_text(
        json.dumps(manifiesto.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ruta


# ---------------------------------------------------------------------------
# Traer documentos
# ---------------------------------------------------------------------------


def descargar(
    doc: Documento,
    cache: str | Path = CACHE_POR_DEFECTO,
    *,
    forzar: bool = False,
    transporte=None,
    respetar_robots: bool = True,
) -> Descarga:
    """Trae un documento a la caché. Si ya está y no se fuerza, no toca la red."""
    if doc.url is None:
        raise ErrorDescarga(
            f"'{doc.id}' no tiene URL en el catálogo. {doc.notas or ''} "
            "Bájalo a mano y adjúntalo con `aula curriculum adjuntar`.".strip()
        )

    cache = Path(cache)
    manifiesto = cargar_manifiesto(cache)
    previa = manifiesto.get(doc.id)
    if previa and not forzar and previa.ruta(cache).exists():
        return previa

    transporte = transporte or _bajar_http
    if respetar_robots and transporte is _bajar_http and not _permitido(doc.url):
        raise ErrorDescarga(
            f"robots.txt de {urllib.parse.urlparse(doc.url).netloc} no permite "
            f"traer {doc.url}. No se descarga."
        )

    contenido, content_type = transporte(doc.url)
    return _guardar(doc, contenido, content_type, cache, manifiesto, origen="red")


def adjuntar(
    doc: Documento,
    ruta_local: str | Path,
    cache: str | Path = CACHE_POR_DEFECTO,
) -> Descarga:
    """Mete en la caché un archivo que ya está en el disco.

    Es la vía para documentos sin URL estable, y la que hace que un PDF bajado a
    mano entre por exactamente el mismo camino que uno descargado: mismo
    manifiesto, mismo sha256, misma licencia, misma extracción. Sin esto, quien
    ya tiene el archivo tendría que esperar a que alguien verifique una URL.
    """
    ruta_local = Path(ruta_local).expanduser()
    if not ruta_local.exists():
        raise ErrorDescarga(f"no encuentro {ruta_local}")
    cache = Path(cache)
    manifiesto = cargar_manifiesto(cache)
    tipo = "application/pdf" if ruta_local.suffix.lower() == ".pdf" else "text/html"
    return _guardar(
        doc, ruta_local.read_bytes(), tipo, cache, manifiesto, origen="archivo"
    )


def _guardar(
    doc: Documento,
    contenido: bytes,
    content_type: str,
    cache: Path,
    manifiesto: Manifiesto,
    origen: Literal["red", "archivo"],
) -> Descarga:
    if not contenido:
        raise ErrorDescarga(f"'{doc.id}' vino vacío")

    destino = cache / doc.nombre_archivo()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(contenido)

    descarga = Descarga(
        id=doc.id,
        archivo=doc.nombre_archivo(),
        sha256=hashlib.sha256(contenido).hexdigest(),
        bytes=len(contenido),
        url=doc.url,
        content_type=content_type,
        descargado_en=_dt.datetime.now(_dt.timezone.utc),
        origen=origen,
        licencia=doc.licencia,
        titulo=doc.titulo or doc.id,
    )
    manifiesto.descargas[doc.id] = descarga
    guardar_manifiesto(manifiesto, cache)
    return descarga


def traer_todos(
    docs: list[Documento],
    cache: str | Path = CACHE_POR_DEFECTO,
    *,
    forzar: bool = False,
    transporte=None,
    al_avanzar=None,
) -> tuple[list[Descarga], list[tuple[str, str]]]:
    """Descarga una lista, con pausa entre peticiones reales.

    Devuelve lo que se trajo y lo que falló, en vez de reventar en el primero:
    que el temario de 7º no exista no es motivo para no importar el de 2º.
    """
    traidas: list[Descarga] = []
    fallos: list[tuple[str, str]] = []
    primera = True
    for doc in docs:
        try:
            en_cache = doc.id in cargar_manifiesto(cache) and not forzar
            if not en_cache and not primera:
                time.sleep(PAUSA)
            descarga = descargar(doc, cache, forzar=forzar, transporte=transporte)
            traidas.append(descarga)
            primera = primera and en_cache
        except (ErrorDescarga, OSError) as exc:
            fallos.append((doc.id, str(exc)))
        if al_avanzar is not None:
            al_avanzar(doc)
    return traidas, fallos


def verificar(cache: str | Path = CACHE_POR_DEFECTO) -> list[str]:
    """Comprueba que la caché cuadra con su manifiesto.

    Una caché que viajó por AirDrop o un zip puede llegar con un archivo a medias,
    y un PDF truncado produce una extracción silenciosamente incompleta. Eso es
    peor que un error.
    """
    cache = Path(cache)
    problemas = []
    for doc_id, descarga in cargar_manifiesto(cache).descargas.items():
        ruta = descarga.ruta(cache)
        if not ruta.exists():
            problemas.append(f"{doc_id}: falta {descarga.archivo}")
            continue
        contenido = ruta.read_bytes()
        if hashlib.sha256(contenido).hexdigest() != descarga.sha256:
            problemas.append(f"{doc_id}: el sha256 no cuadra, el archivo cambió")
        elif len(contenido) != descarga.bytes:  # pragma: no cover - implícito
            problemas.append(f"{doc_id}: el tamaño no cuadra")
    return problemas


def copiar_cache(origen: str | Path, destino: str | Path) -> int:  # pragma: no cover
    """Copia una caché entera. El manifiesto viaja con ella, que es el punto."""
    origen, destino = Path(origen), Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    copiados = 0
    for archivo in origen.iterdir():
        if archivo.is_file():
            shutil.copy2(archivo, destino / archivo.name)
            copiados += 1
    return copiados


# ---------------------------------------------------------------------------
# Transporte real
# ---------------------------------------------------------------------------


def _bajar_http(url: str) -> tuple[bytes, str]:
    """Transporte real. En los tests se inyecta otro: ninguno toca la red."""
    peticion = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    try:
        with urllib.request.urlopen(peticion, timeout=TIEMPO_LIMITE) as respuesta:
            return respuesta.read(), respuesta.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raise ErrorDescarga(f"{exc.code} al pedir {url}") from exc
    except urllib.error.URLError as exc:
        raise ErrorDescarga(f"no se pudo conectar con {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ErrorDescarga(f"tiempo agotado esperando a {url}") from exc


def _permitido(url: str) -> bool:
    """Consulta robots.txt. Si no se puede leer, se asume permitido."""
    partes = urllib.parse.urlparse(url)
    lector = urllib.robotparser.RobotFileParser()
    lector.set_url(f"{partes.scheme}://{partes.netloc}/robots.txt")
    try:
        lector.read()
    except Exception:  # noqa: BLE001 - sin robots.txt legible, se sigue adelante
        return True
    return lector.can_fetch(AGENTE, url)
