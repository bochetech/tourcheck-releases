"""Genera un PDF válido mínimo, sin dependencias.

Los tests del importador necesitan un PDF **de verdad**: la propiedad que hay que
verificar es que el número de página sobrevive desde el documento hasta
`Fuente.pagina`, y eso no se puede comprobar con un texto simulado. Escribir el
PDF a mano es más barato y más honesto que añadir una dependencia de generación
solo para los tests.
"""

from __future__ import annotations


def _escapar(texto: str) -> str:
    return texto.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _contenido(lineas: list[str]) -> bytes:
    partes = ["BT", "/F1 11 Tf", "14 TL", "40 750 Td"]
    for linea in lineas:
        partes.append(f"({_escapar(linea)}) Tj")
        partes.append("T*")
    partes.append("ET")
    return "\n".join(partes).encode("latin-1", "replace")


def pdf_de_paginas(paginas: list[list[str]]) -> bytes:
    """Un PDF con una página por lista de líneas. Fuente estándar, sin incrustar."""
    objetos: list[bytes] = []

    def agregar(cuerpo: bytes) -> int:
        objetos.append(cuerpo)
        return len(objetos)

    fuente = agregar(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    ids_pagina: list[int] = []
    ids_contenido: list[int] = []
    for lineas in paginas:
        datos = _contenido(lineas)
        ids_contenido.append(
            agregar(b"<< /Length " + str(len(datos)).encode() + b" >>\nstream\n" + datos + b"\nendstream")
        )
        ids_pagina.append(agregar(b"PLACEHOLDER"))

    id_paginas = agregar(b"PLACEHOLDER")
    for pagina_id, contenido_id in zip(ids_pagina, ids_contenido):
        objetos[pagina_id - 1] = (
            b"<< /Type /Page /Parent " + str(id_paginas).encode() + b" 0 R "
            b"/MediaBox [0 0 612 792] /Resources << /Font << /F1 "
            + str(fuente).encode()
            + b" 0 R >> >> /Contents "
            + str(contenido_id).encode()
            + b" 0 R >>"
        )
    hijos = b" ".join(str(i).encode() + b" 0 R" for i in ids_pagina)
    objetos[id_paginas - 1] = (
        b"<< /Type /Pages /Kids [" + hijos + b"] /Count " + str(len(ids_pagina)).encode() + b" >>"
    )
    id_raiz = agregar(b"<< /Type /Catalog /Pages " + str(id_paginas).encode() + b" 0 R >>")

    salida = bytearray(b"%PDF-1.4\n")
    posiciones = [0]
    for numero, cuerpo in enumerate(objetos, start=1):
        posiciones.append(len(salida))
        salida += str(numero).encode() + b" 0 obj\n" + cuerpo + b"\nendobj\n"

    inicio_xref = len(salida)
    salida += b"xref\n0 " + str(len(objetos) + 1).encode() + b"\n"
    salida += b"0000000000 65535 f \n"
    for pos in posiciones[1:]:
        salida += f"{pos:010d} 00000 n \n".encode()
    salida += (
        b"trailer\n<< /Size " + str(len(objetos) + 1).encode()
        + b" /Root " + str(id_raiz).encode() + b" 0 R >>\nstartxref\n"
        + str(inicio_xref).encode() + b"\n%%EOF\n"
    )
    return bytes(salida)
