"""De qué asignatura y nivel es un documento, cuando el documento no lo dice en cada línea.

Existe por un hallazgo contra un documento real: en un **Programa de Estudio**
del MINEDUC los objetivos no se escriben `MA05 OA 01` sino `OA 1` a secas. Y es
razonable: el documento entero es de una asignatura y un nivel, así que repetir
el prefijo 206 veces sería ruido. El prefijo no está escrito, está implícito en
la portada.

Eso obliga a resolver la asignatura y el nivel **una vez por documento** para
poder completar los códigos escuetos a su forma canónica. Y a resolverlo con
cuidado: si nos equivocamos de nivel, todos los objetivos del documento quedan
mal etiquetados a la vez.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel

#: Cuánto texto del principio se mira. La portada y la presentación bastan; más
#: adelante el documento cita otros niveles y ensucia la detección.
VENTANA = 6_000


class ContextoDocumento(BaseModel):
    """Asignatura y nivel de un documento, con de dónde salió cada uno.

    `origen` importa: no es lo mismo que el nivel venga del catálogo (seguro) a
    que lo haya adivinado una expresión regular sobre la portada (revisable). Un
    nivel equivocado etiqueta mal el documento entero, así que quien lo mire
    tiene que poder ver de dónde salió.
    """

    asignatura: str | None = None
    nivel: str | None = None
    origen_asignatura: str = "sin determinar"
    origen_nivel: str = "sin determinar"

    @property
    def completo(self) -> bool:
        return bool(self.asignatura and self.nivel)

    def __str__(self) -> str:  # pragma: no cover - conveniencia
        return (
            f"{self.asignatura or '??'} nivel {self.nivel or '??'} "
            f"({self.origen_asignatura} / {self.origen_nivel})"
        )


#: Siglas de asignatura del currículo chileno, con las palabras que las delatan.
#: El orden importa: la primera que aparezca en el texto gana.
ASIGNATURAS: list[tuple[str, tuple[str, ...]]] = [
    ("MA", ("matematica",)),
    ("LE", ("lenguaje y comunicacion", "lengua y literatura", "lenguaje")),
    ("CN", ("ciencias naturales", "biologia", "fisica", "quimica")),
    ("HI", ("historia, geografia y ciencias sociales", "historia")),
    ("IN", ("ingles", "idioma extranjero")),
    ("AR", ("artes visuales",)),
    ("MU", ("musica",)),
    ("EF", ("educacion fisica y salud", "educacion fisica")),
    ("TE", ("tecnologia",)),
    ("OR", ("orientacion",)),
]

_ORDINALES = {
    "primero": 1, "primer": 1, "segundo": 2, "tercero": 3, "tercer": 3,
    "cuarto": 4, "quinto": 5, "sexto": 6, "septimo": 7, "octavo": 8,
}

#: "5º básico", "5° basico", "5 basico"
_NIVEL_NUMERICO = re.compile(r"\b([1-8])\s*[ºo°]?\s*b[áa]sico\b")
#: "quinto básico"
_NIVEL_PALABRA = re.compile(
    r"\b(" + "|".join(_ORDINALES) + r")\s+(?:a[ñn]o\s+)?b[áa]sico\b"
)
#: Media: "I medio" … "IV medio", "1º medio". Se guarda como "1M".."4M", que es
#: lo que usan los propios códigos del MINEDUC (`MA1M OA 01`).
_MEDIA_ROMANO = re.compile(r"\b(IV|III|II|I)\s*[ºo°]?\s*medio\b")
_MEDIA_NUMERO = re.compile(r"\b([1-4])\s*[ºo°]?\s*medio\b")
_ROMANOS = {"I": 1, "II": 2, "III": 3, "IV": 4}


def _sin_tildes(texto: str) -> str:
    plano = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in plano if unicodedata.category(c) != "Mn")


def detectar_asignatura(texto: str) -> str | None:
    """Sigla de la asignatura, por la primera mención en la portada."""
    plano = _sin_tildes(texto[:VENTANA])
    mejor: tuple[int, str] | None = None
    for sigla, palabras in ASIGNATURAS:
        for palabra in palabras:
            pos = plano.find(_sin_tildes(palabra))
            if pos != -1 and (mejor is None or pos < mejor[0]):
                mejor = (pos, sigla)
    return mejor[1] if mejor else None


def detectar_nivel(texto: str) -> str | None:
    """Nivel en la forma del modelo: "01".."08" en básica, "1M".."4M" en media."""
    ventana = texto[:VENTANA]
    plano = _sin_tildes(ventana)

    candidatos: list[tuple[int, str]] = []
    if (m := _NIVEL_NUMERICO.search(plano)):
        candidatos.append((m.start(), f"{int(m.group(1)):02d}"))
    if (m := _NIVEL_PALABRA.search(plano)):
        candidatos.append((m.start(), f"{_ORDINALES[m.group(1)]:02d}"))
    # El romano se busca sobre el original: en minúsculas, "I medio" y "i medio"
    # se confunden con cualquier palabra suelta.
    if (m := _MEDIA_ROMANO.search(ventana)):
        candidatos.append((m.start(), f"{_ROMANOS[m.group(1)]}M"))
    if (m := _MEDIA_NUMERO.search(plano)):
        candidatos.append((m.start(), f"{int(m.group(1))}M"))

    return min(candidatos)[1] if candidatos else None


def detectar(
    texto: str,
    *,
    asignatura: str | None = None,
    nivel: str | None = None,
) -> ContextoDocumento:
    """Resuelve el contexto. Lo que se pasa a mano manda sobre lo detectado.

    El orden no es negociable: el catálogo y la línea de comandos son afirmaciones
    de una persona, y una expresión regular sobre una portada es una conjetura.
    """
    detectada = detectar_asignatura(texto)
    detectado = detectar_nivel(texto)
    return ContextoDocumento(
        asignatura=asignatura or detectada,
        nivel=nivel or detectado,
        origen_asignatura="declarada" if asignatura else (
            "detectada en la portada" if detectada else "sin determinar"
        ),
        origen_nivel="declarado" if nivel else (
            "detectado en la portada" if detectado else "sin determinar"
        ),
    )
