"""Operaciones de reparación: el vocabulario cerrado con el que se arregla un plan.

El modelo **no reescribe el YAML**. Propone operaciones de esta lista, el código
las valida contra el currículo real y solo entonces las aplica. Es el mismo
principio que el contrato de herramientas del tutor: si la IA solo puede actuar
con un vocabulario cerrado, no puede romper el plan aunque alucine.

Cada operación devuelve por qué se rechazó cuando no procede, y ese motivo vuelve
al modelo como retroalimentación en la siguiente vuelta del bucle.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from aula.curriculum.model import Curriculum, Fuente, Licencia, Objetivo


class _Base(BaseModel):
    motivo: str = ""
    """Por qué el modelo propone esto. Queda en la bitácora para poder auditarlo."""


class QuitarPrerequisito(_Base):
    op: Literal["quitar_prerequisito"] = "quitar_prerequisito"
    objetivo: str
    prerequisito: str


class CorregirPrerequisito(_Base):
    op: Literal["corregir_prerequisito"] = "corregir_prerequisito"
    objetivo: str
    de: str
    a: str


class FijarCampo(_Base):
    op: Literal["fijar_campo"] = "fijar_campo"
    objetivo: str
    campo: Literal["asignatura", "nivel", "unidad", "en_temario_examen", "horas_estimadas"]
    valor: str | float | bool


class AgregarItems(_Base):
    op: Literal["agregar_items"] = "agregar_items"
    objetivo: str
    items: list[str]


class FijarFuente(_Base):
    op: Literal["fijar_fuente"] = "fijar_fuente"
    objetivo: str
    doc: str
    pagina: int | None = None
    url: str | None = None


class FijarLicencia(_Base):
    op: Literal["fijar_licencia"] = "fijar_licencia"
    objetivo: str
    tipo: str
    url: str | None = None
    puede_redistribuir: bool = False


class ReescribirTexto(_Base):
    op: Literal["reescribir_texto"] = "reescribir_texto"
    objetivo: str
    texto: str


class ReescalarHoras(_Base):
    op: Literal["reescalar_horas"] = "reescalar_horas"
    nivel: str
    asignatura: str
    factor: float


class FusionarDuplicados(_Base):
    op: Literal["fusionar_duplicados"] = "fusionar_duplicados"
    codigo: str


class AgregarObjetivo(_Base):
    op: Literal["agregar_objetivo"] = "agregar_objetivo"
    objetivo: Objetivo


class FijarMeta(_Base):
    op: Literal["fijar_meta"] = "fijar_meta"
    campo: Literal["version", "vigencia_desde", "vigencia_hasta"]
    valor: str


Operacion = Annotated[
    Union[
        QuitarPrerequisito,
        CorregirPrerequisito,
        FijarCampo,
        AgregarItems,
        FijarFuente,
        FijarLicencia,
        ReescribirTexto,
        ReescalarHoras,
        FusionarDuplicados,
        AgregarObjetivo,
        FijarMeta,
    ],
    Field(discriminator="op"),
]


OperacionSinAgregado = Annotated[
    Union[
        QuitarPrerequisito,
        CorregirPrerequisito,
        FijarCampo,
        AgregarItems,
        FijarFuente,
        FijarLicencia,
        ReescribirTexto,
        ReescalarHoras,
        FusionarDuplicados,
        FijarMeta,
    ],
    Field(discriminator="op"),
]
"""El vocabulario sin `agregar_objetivo`, para modelos con poco contexto."""


class Aplicacion(BaseModel):
    """Qué pasó con una operación propuesta."""

    operacion: dict
    aplicada: bool
    rechazo: str | None = None


def _buscar(curriculum: Curriculum, codigo: str) -> Objetivo | None:
    for o in curriculum.objetivos:
        if o.codigo == codigo:
            return o
    return None


def _en_temario(curriculum: Curriculum, codigo: str) -> bool:
    return any(codigo in codigos for codigos in curriculum.temario.values())


def aplicar_una(curriculum: Curriculum, op) -> str | None:
    """Aplica una operación in situ. Devuelve el motivo de rechazo, o None si se aplicó."""

    if isinstance(op, FijarMeta):
        if not op.valor.strip():
            return "el valor está vacío"
        setattr(curriculum, op.campo, op.valor)
        return None

    if isinstance(op, ReescalarHoras):
        if not 0.01 <= op.factor <= 100:
            return f"factor {op.factor} fuera de un rango razonable"
        objetivos = curriculum.objetivos_de(op.nivel, op.asignatura)
        if not objetivos:
            return f"no hay objetivos de '{op.asignatura}' en el nivel '{op.nivel}'"
        for objetivo in objetivos:
            objetivo.horas_estimadas = round(objetivo.horas_estimadas * op.factor, 2)
        return None

    if isinstance(op, FusionarDuplicados):
        copias = [o for o in curriculum.objetivos if o.codigo == op.codigo]
        if len(copias) < 2:
            return f"'{op.codigo}' no está duplicado"
        # Se conserva la copia de mayor confianza y se le suma lo de las demás.
        copias.sort(key=lambda o: o.confianza, reverse=True)
        superviviente, resto = copias[0], copias[1:]
        for otra in resto:
            for pre in otra.prerequisitos:
                if pre not in superviviente.prerequisitos:
                    superviviente.prerequisitos.append(pre)
            for item in otra.items:
                if item not in superviviente.items:
                    superviviente.items.append(item)
            superviviente.en_temario_examen |= otra.en_temario_examen
            if superviviente.fuente is None:
                superviviente.fuente = otra.fuente
            curriculum.objetivos.remove(otra)
        return None

    if isinstance(op, AgregarObjetivo):
        if _buscar(curriculum, op.objetivo.codigo) is not None:
            return f"'{op.objetivo.codigo}' ya existe"
        curriculum.objetivos.append(op.objetivo)
        return None

    # A partir de aquí todas actúan sobre un objetivo concreto.
    objetivo = _buscar(curriculum, op.objetivo)
    if objetivo is None:
        return f"el objetivo '{op.objetivo}' no existe"

    if isinstance(op, QuitarPrerequisito):
        if op.prerequisito not in objetivo.prerequisitos:
            return f"'{objetivo.codigo}' no tiene el prerrequisito '{op.prerequisito}'"
        objetivo.prerequisitos.remove(op.prerequisito)
        return None

    if isinstance(op, CorregirPrerequisito):
        if op.de not in objetivo.prerequisitos:
            return f"'{objetivo.codigo}' no tiene el prerrequisito '{op.de}'"
        if _buscar(curriculum, op.a) is None:
            return f"el prerrequisito de destino '{op.a}' tampoco existe"
        if op.a == objetivo.codigo:
            return "un objetivo no puede ser prerrequisito de sí mismo"
        objetivo.prerequisitos = [op.a if p == op.de else p for p in objetivo.prerequisitos]
        return None

    if isinstance(op, FijarCampo):
        if op.campo == "en_temario_examen":
            if _en_temario(curriculum, objetivo.codigo) and not op.valor:
                return "está en el temario oficial: no se puede desmarcar"
            objetivo.en_temario_examen = bool(op.valor)
            return None
        if op.campo == "horas_estimadas":
            try:
                horas = float(op.valor)
            except (TypeError, ValueError):
                return f"'{op.valor}' no es un número de horas"
            if horas < 0:
                return "las horas no pueden ser negativas"
            objetivo.horas_estimadas = horas
            return None
        valor = str(op.valor).strip()
        if not valor:
            return f"el campo '{op.campo}' no puede quedar vacío"
        setattr(objetivo, op.campo, valor)
        return None

    if isinstance(op, AgregarItems):
        nuevos = [i for i in op.items if i and i not in objetivo.items]
        if not nuevos:
            return "no aporta ningún ítem nuevo"
        objetivo.items.extend(nuevos)
        return None

    if isinstance(op, FijarFuente):
        if not op.doc.strip():
            return "el documento fuente no puede estar vacío"
        objetivo.fuente = Fuente(doc=op.doc.strip(), pagina=op.pagina, url=op.url)
        return None

    if isinstance(op, FijarLicencia):
        if not op.tipo.strip() or op.tipo == "desconocida":
            return "hay que declarar una licencia concreta"
        objetivo.licencia = Licencia(
            tipo=op.tipo.strip(), url=op.url, puede_redistribuir=op.puede_redistribuir
        )
        return None

    if isinstance(op, ReescribirTexto):
        nuevo = op.texto.strip()
        if len(nuevo) < 10:
            return "el texto reescrito es demasiado corto para ser un objetivo"
        # El texto oficial nunca se pierde: si no estaba guardado, se guarda ahora.
        if objetivo.fuente is not None and not objetivo.fuente.doc.startswith("[reescrito]"):
            objetivo.resumen = objetivo.resumen or objetivo.texto
        objetivo.texto = nuevo
        return None

    return f"operación no reconocida: {type(op).__name__}"


def aplicar(curriculum: Curriculum, operaciones: list) -> list[Aplicacion]:
    """Aplica una tanda de operaciones sobre una copia y reporta qué pasó con cada una.

    Muta el `curriculum` recibido: el bucle de reparación trabaja siempre sobre una
    copia para poder descartar una vuelta entera que empeore las cosas.
    """
    resultado: list[Aplicacion] = []
    for op in operaciones:
        rechazo = aplicar_una(curriculum, op)
        resultado.append(
            Aplicacion(
                operacion=op.model_dump(mode="json"),
                aplicada=rechazo is None,
                rechazo=rechazo,
            )
        )
    return resultado
