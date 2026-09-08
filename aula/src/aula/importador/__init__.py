"""Importador de currículo: de documento oficial a modelo canónico.

Está partido en dos programas unidos por una caché en disco:

    fetch  ──────────────►  datos/fuentes/  ──────────────►  extract
    (red, una vez)          caché + manifiesto              (sin red, cuantas veces haga falta)

No es una separación estética. Descargar necesita red y permiso; entender necesita
iterar el prompt veinte veces. Juntarlos obliga a volver a bajar el PDF cada vez
que se ajusta una instrucción, y a que quien desarrolla la extracción tenga acceso
a la red del ministerio. Separados, la caché **es el fixture**: se comparte la
carpeta y la extracción se desarrolla offline contra documentos reales.

Y no hay selectores. El documento se lleva a texto plano y el modelo saca los
objetivos con un esquema JSON como decodificación restringida. La procedencia
—página, documento, URL— **no se le pregunta al modelo**: se calcula con una
expresión regular sobre el documento antes de la primera llamada. Un modelo puede
alucinar un código; no puede alucinar en qué página del PDF estaba.
"""

from aula.importador.catalogo import Documento, documentos
from aula.importador.codigos import CodigoEnDocumento, indexar_codigos, normalizar
from aula.importador.texto import DocumentoTexto, Pagina, SinCapaDeTexto, leer_texto
from aula.importador.trozos import Trozo, trocear

__all__ = [
    "CodigoEnDocumento",
    "Documento",
    "DocumentoTexto",
    "Pagina",
    "SinCapaDeTexto",
    "Trozo",
    "documentos",
    "indexar_codigos",
    "leer_texto",
    "normalizar",
    "trocear",
]
