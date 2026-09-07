"""Validador del plan de estudios: 12 reglas duras.

El consumidor principal de este validador **no es una persona**: es el bucle de
auto-reparación. Por eso cada `Hallazgo` lleva, además del mensaje humano, una
`reparacion` accionable y un `datos` estructurado que la IA puede aplicar sin
tener que interpretar prosa. Solo lo que el bucle no logra cerrar llega a la cola
de excepciones del padre.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum

from pydantic import BaseModel, Field

from aula.curriculum.model import Curriculum, Objetivo

# Profundidad de cadena de prerrequisitos por encima de la cual casi siempre hay
# un error de extracción, no un currículo genuinamente profundo.
MAX_PROFUNDIDAD = 25

# Tolerancia entre las horas estimadas de los objetivos y el plan de estudio oficial.
TOLERANCIA_HORAS = 0.10

# Índice de legibilidad Fernández Huerta mínimo esperado según el nivel.
LEGIBILIDAD_MINIMA = {"basica_inicial": 70.0, "basica_superior": 60.0, "media": 50.0}


class Severidad(str, Enum):
    BLOQUEANTE = "bloqueante"
    ADVERTENCIA = "advertencia"


class Hallazgo(BaseModel):
    """Un problema detectado, formulado para que una máquina pueda arreglarlo."""

    regla: int
    codigo_regla: str
    severidad: Severidad
    mensaje: str
    objetivo: str | None = None
    reparacion: str | None = None
    datos: dict = Field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - conveniencia de depuración
        donde = f" [{self.objetivo}]" if self.objetivo else ""
        return f"R{self.regla:02d} {self.severidad.value}{donde}: {self.mensaje}"


class Resultado(BaseModel):
    """Resultado completo de una validación."""

    hallazgos: list[Hallazgo] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """El plan es utilizable si no queda ningún hallazgo bloqueante."""
        return not self.bloqueantes

    @property
    def bloqueantes(self) -> list[Hallazgo]:
        return [h for h in self.hallazgos if h.severidad is Severidad.BLOQUEANTE]

    @property
    def advertencias(self) -> list[Hallazgo]:
        return [h for h in self.hallazgos if h.severidad is Severidad.ADVERTENCIA]

    def por_regla(self, regla: int) -> list[Hallazgo]:
        return [h for h in self.hallazgos if h.regla == regla]


# ---------------------------------------------------------------------------
# Legibilidad en español (índice Fernández Huerta)
# ---------------------------------------------------------------------------

_VOCALES_FUERTES = set("aeoáéó")
_VOCALES_DEBILES = set("iuü")
_VOCALES_DEBILES_TONICAS = set("íú")
_VOCALES = _VOCALES_FUERTES | _VOCALES_DEBILES | _VOCALES_DEBILES_TONICAS


def _normalizar(palabra: str) -> str:
    return palabra.lower()


def contar_silabas(palabra: str) -> int:
    """Cuenta sílabas de una palabra española por grupos vocálicos e hiatos.

    Es una heurística, no un silabeador completo, pero basta para un índice de
    legibilidad: los errores se promedian sobre cientos de palabras.
    """
    p = _normalizar(palabra)
    p = "".join(ch for ch in p if ch.isalpha())
    if not p:
        return 0

    silabas = 0
    i = 0
    while i < len(p):
        if p[i] not in _VOCALES:
            i += 1
            continue
        # Grupo vocálico maximal.
        j = i
        while j < len(p) and p[j] in _VOCALES:
            j += 1
        grupo = p[i:j]
        silabas += 1
        # Cada hiato dentro del grupo abre una sílaba más.
        for k in range(len(grupo) - 1):
            a, b = grupo[k], grupo[k + 1]
            dos_fuertes = a in _VOCALES_FUERTES and b in _VOCALES_FUERTES
            debil_tonica = a in _VOCALES_DEBILES_TONICAS or b in _VOCALES_DEBILES_TONICAS
            if dos_fuertes or debil_tonica:
                silabas += 1
        i = j
    return max(silabas, 1)


def fernandez_huerta(texto: str) -> float | None:
    """Índice de legibilidad Fernández Huerta (adaptación española del Flesch).

    100 = muy fácil, 0 = muy difícil. Devuelve None si no hay texto suficiente
    para que el número signifique algo.
    """
    palabras = re.findall(r"[^\W\d_]+", texto, flags=re.UNICODE)
    if len(palabras) < 5:
        return None
    frases = [f for f in re.split(r"[.;:!?\n]+", texto) if f.strip()]
    n_frases = max(len(frases), 1)
    silabas = sum(contar_silabas(w) for w in palabras)

    p = silabas * 100.0 / len(palabras)  # sílabas por 100 palabras
    f = n_frases * 100.0 / len(palabras)  # frases por 100 palabras
    return 206.84 - 0.60 * p - 1.02 * f


def _banda_de_nivel(nivel: str) -> str | None:
    """Traduce un nivel escolar a la banda de legibilidad esperada."""
    digitos = re.sub(r"\D", "", nivel)
    if not digitos:
        return None
    n = int(digitos)
    if n <= 4:
        return "basica_inicial"
    if n <= 8:
        return "basica_superior"
    return "media"


# ---------------------------------------------------------------------------
# Las 12 reglas
# ---------------------------------------------------------------------------


def _r01_aciclico(c: Curriculum) -> list[Hallazgo]:
    """Un ciclo en los prerrequisitos deja al alumno bloqueado para siempre."""
    indice = c.por_codigo()
    ESTADO_NUEVO, ESTADO_EN_CURSO, ESTADO_LISTO = 0, 1, 2
    estado: dict[str, int] = {}
    hallazgos: list[Hallazgo] = []
    reportados: set[tuple[str, ...]] = set()

    def visitar(codigo: str, camino: list[str]) -> None:
        estado[codigo] = ESTADO_EN_CURSO
        camino.append(codigo)
        for pre in indice[codigo].prerequisitos if codigo in indice else []:
            if pre not in indice:
                continue  # lo reporta la regla 2
            st = estado.get(pre, ESTADO_NUEVO)
            if st == ESTADO_EN_CURSO:
                ciclo = camino[camino.index(pre) :] + [pre]
                clave = tuple(sorted(set(ciclo)))
                if clave not in reportados:
                    reportados.add(clave)
                    hallazgos.append(
                        Hallazgo(
                            regla=1,
                            codigo_regla="R01_CICLO",
                            severidad=Severidad.BLOQUEANTE,
                            objetivo=codigo,
                            mensaje=f"ciclo de prerrequisitos: {' -> '.join(ciclo)}",
                            reparacion=(
                                "Rompe el ciclo eliminando el prerrequisito que va del "
                                "objetivo más avanzado al más básico. En una progresión "
                                "correcta los prerrequisitos apuntan siempre hacia atrás."
                            ),
                            datos={"ciclo": ciclo},
                        )
                    )
            elif st == ESTADO_NUEVO:
                visitar(pre, camino)
        camino.pop()
        estado[codigo] = ESTADO_LISTO

    for o in c.objetivos:
        if estado.get(o.codigo, ESTADO_NUEVO) == ESTADO_NUEVO:
            visitar(o.codigo, [])
    return hallazgos


def _r02_prerequisitos_existen(c: Curriculum) -> list[Hallazgo]:
    """Un prerrequisito que no existe suele ser un error de transcripción."""
    indice = c.por_codigo()
    hallazgos = []
    for o in c.objetivos:
        for pre in o.prerequisitos:
            if pre not in indice:
                hallazgos.append(
                    Hallazgo(
                        regla=2,
                        codigo_regla="R02_PREREQ_INEXISTENTE",
                        severidad=Severidad.BLOQUEANTE,
                        objetivo=o.codigo,
                        mensaje=f"el prerrequisito '{pre}' no existe en el currículo",
                        reparacion=(
                            f"Corrige o elimina la referencia '{pre}' en el objetivo "
                            f"'{o.codigo}'. Si es un error de tipeo, sustitúyela por el "
                            "código real; si el objetivo no está importado todavía, "
                            "elimínala."
                        ),
                        datos={"objetivo": o.codigo, "prerequisito_roto": pre},
                    )
                )
    return hallazgos


def _r03_sin_huerfanos(c: Curriculum) -> list[Hallazgo]:
    """Un objetivo sin asignatura o sin nivel se pierde del plan."""
    hallazgos = []
    for o in c.objetivos:
        faltan = [campo for campo in ("asignatura", "nivel") if not getattr(o, campo)]
        if faltan:
            hallazgos.append(
                Hallazgo(
                    regla=3,
                    codigo_regla="R03_HUERFANO",
                    severidad=Severidad.BLOQUEANTE,
                    objetivo=o.codigo,
                    mensaje=f"objetivo huérfano: falta {', '.join(faltan)}",
                    reparacion=(
                        f"Asigna {' y '.join(faltan)} al objetivo '{o.codigo}' a partir "
                        "del documento fuente."
                    ),
                    datos={"campos_faltantes": faltan},
                )
            )
    return hallazgos


def _r04_tiene_evaluacion(c: Curriculum) -> list[Hallazgo]:
    """Lo que no se puede evaluar no se puede dominar."""
    return [
        Hallazgo(
            regla=4,
            codigo_regla="R04_SIN_ITEMS",
            severidad=Severidad.BLOQUEANTE,
            objetivo=o.codigo,
            mensaje="el objetivo no tiene ningún ítem de evaluación",
            reparacion=(
                f"Genera al menos un ítem para '{o.codigo}' que evalúe exactamente lo "
                f"que dice su texto: «{o.texto[:120]}»"
            ),
            datos={"objetivo": o.codigo, "texto": o.texto},
        )
        for o in c.objetivos
        if not o.items
    ]


def _r05_trazabilidad(c: Curriculum) -> list[Hallazgo]:
    """Sin fuente no se puede auditar si la IA lo extrajo o lo inventó."""
    hallazgos = []
    for o in c.objetivos:
        if o.fuente is None or not o.fuente.doc:
            hallazgos.append(
                Hallazgo(
                    regla=5,
                    codigo_regla="R05_SIN_FUENTE",
                    severidad=Severidad.BLOQUEANTE,
                    objetivo=o.codigo,
                    mensaje="el objetivo no declara documento fuente",
                    reparacion=(
                        f"Añade la fuente de '{o.codigo}': documento, página y URL de "
                        "donde se extrajo. Si no se puede determinar, el objetivo es "
                        "sospechoso de haber sido inventado y debe eliminarse."
                    ),
                    datos={"objetivo": o.codigo},
                )
            )
    return hallazgos


def _r06_cobertura_temario(c: Curriculum) -> list[Hallazgo]:
    """El temario oficial es el blanco mínimo: no puede quedar nada fuera."""
    indice = c.por_codigo()
    hallazgos = []
    for nivel, codigos in c.temario.items():
        faltantes = [cod for cod in codigos if cod not in indice]
        if faltantes:
            hallazgos.append(
                Hallazgo(
                    regla=6,
                    codigo_regla="R06_TEMARIO_INCOMPLETO",
                    severidad=Severidad.BLOQUEANTE,
                    mensaje=(
                        f"el nivel '{nivel}' no cubre {len(faltantes)} objetivos del "
                        f"temario oficial: {', '.join(faltantes[:5])}"
                        + ("…" if len(faltantes) > 5 else "")
                    ),
                    reparacion=(
                        "Vuelve a extraer estos objetivos del documento oficial; están "
                        "en el temario del examen pero no en el plan importado."
                    ),
                    datos={"nivel": nivel, "faltantes": faltantes},
                )
            )
        no_marcados = [
            cod for cod in codigos if cod in indice and not indice[cod].en_temario_examen
        ]
        if no_marcados:
            hallazgos.append(
                Hallazgo(
                    regla=6,
                    codigo_regla="R06_TEMARIO_SIN_MARCAR",
                    severidad=Severidad.ADVERTENCIA,
                    mensaje=(
                        f"{len(no_marcados)} objetivos del temario del nivel '{nivel}' "
                        "no están marcados como `en_temario_examen`"
                    ),
                    reparacion="Pon `en_temario_examen: true` en estos objetivos.",
                    datos={"nivel": nivel, "codigos": no_marcados},
                )
            )
    return hallazgos


def _r07_horas_cuadran(c: Curriculum) -> list[Hallazgo]:
    """Horas que no cuadran delatan unidades infladas o vacías."""
    hallazgos = []
    for nivel, por_asignatura in c.plan_horas.items():
        for asignatura, horas_oficiales in por_asignatura.items():
            objetivos = c.objetivos_de(nivel, asignatura)
            if not objetivos:
                continue
            suma = sum(o.horas_estimadas for o in objetivos)
            if horas_oficiales <= 0:
                continue
            desvio = abs(suma - horas_oficiales) / horas_oficiales
            if desvio > TOLERANCIA_HORAS:
                hallazgos.append(
                    Hallazgo(
                        regla=7,
                        codigo_regla="R07_HORAS_DESCUADRADAS",
                        severidad=Severidad.ADVERTENCIA,
                        mensaje=(
                            f"{asignatura} de {nivel}: las horas estimadas suman "
                            f"{suma:.1f} frente a {horas_oficiales:.1f} del plan oficial "
                            f"({desvio:.0%} de desvío)"
                        ),
                        reparacion=(
                            "Reescala `horas_estimadas` de los objetivos de esta "
                            "asignatura y nivel para que sumen las horas oficiales, "
                            "manteniendo la proporción relativa entre ellos."
                        ),
                        datos={
                            "nivel": nivel,
                            "asignatura": asignatura,
                            "suma_actual": suma,
                            "horas_oficiales": horas_oficiales,
                            "factor_sugerido": (
                                horas_oficiales / suma if suma > 0 else None
                            ),
                        },
                    )
                )
    return hallazgos


def _r08_sin_duplicados(c: Curriculum) -> list[Hallazgo]:
    """Un código duplicado rompe el modelo de dominio del estudiante."""
    vistos: dict[str, int] = {}
    for o in c.objetivos:
        vistos[o.codigo] = vistos.get(o.codigo, 0) + 1
    return [
        Hallazgo(
            regla=8,
            codigo_regla="R08_DUPLICADO",
            severidad=Severidad.BLOQUEANTE,
            objetivo=codigo,
            mensaje=f"el código '{codigo}' aparece {n} veces",
            reparacion=(
                f"Fusiona las {n} entradas de '{codigo}' en una sola, uniendo sus "
                "prerrequisitos e ítems y quedándote con el texto de la fuente más "
                "fiable."
            ),
            datos={"codigo": codigo, "repeticiones": n},
        )
        for codigo, n in sorted(vistos.items())
        if n > 1
    ]


def _r09_profundidad(c: Curriculum) -> list[Hallazgo]:
    """Cadenas absurdamente largas suelen ser mala extracción, no profundidad real."""
    indice = c.por_codigo()
    memo: dict[str, int] = {}
    en_curso: set[str] = set()

    def profundidad(codigo: str) -> int:
        if codigo in memo:
            return memo[codigo]
        if codigo in en_curso or codigo not in indice:
            return 0  # ciclo: ya lo reporta la regla 1
        en_curso.add(codigo)
        pres = [p for p in indice[codigo].prerequisitos if p in indice]
        d = 1 + max((profundidad(p) for p in pres), default=0)
        en_curso.discard(codigo)
        memo[codigo] = d
        return d

    hallazgos = []
    for o in c.objetivos:
        d = profundidad(o.codigo)
        if d > MAX_PROFUNDIDAD:
            hallazgos.append(
                Hallazgo(
                    regla=9,
                    codigo_regla="R09_CADENA_LARGA",
                    severidad=Severidad.ADVERTENCIA,
                    objetivo=o.codigo,
                    mensaje=(
                        f"cadena de {d} prerrequisitos encadenados (máximo esperado "
                        f"{MAX_PROFUNDIDAD})"
                    ),
                    reparacion=(
                        "Revisa la cadena: casi siempre significa que se encadenaron "
                        "objetivos que en realidad son independientes. Deja solo los "
                        "prerrequisitos verdaderamente necesarios e inmediatos."
                    ),
                    datos={"objetivo": o.codigo, "profundidad": d},
                )
            )
    return hallazgos


def _r10_licencia(c: Curriculum) -> list[Hallazgo]:
    """Cada recurso arrastra su licencia: decide qué se puede redistribuir."""
    hallazgos = []
    for o in c.objetivos:
        lic = o.licencia or c.licencia_por_defecto
        if lic is None or lic.tipo == "desconocida":
            hallazgos.append(
                Hallazgo(
                    regla=10,
                    codigo_regla="R10_SIN_LICENCIA",
                    severidad=Severidad.ADVERTENCIA,
                    objetivo=o.codigo,
                    mensaje="el objetivo no declara licencia conocida",
                    reparacion=(
                        "Registra la licencia del recurso de origen. En "
                        "curriculumnacional.cl la licencia va por recurso: conviven "
                        "CC BY-SA y «todos los derechos reservados»."
                    ),
                    datos={"objetivo": o.codigo},
                )
            )
    return hallazgos


def _r11_legibilidad(c: Curriculum) -> list[Hallazgo]:
    """Un objetivo de 2° básico redactado para adultos no le sirve al niño."""
    hallazgos = []
    for o in c.objetivos:
        banda = _banda_de_nivel(o.nivel)
        if banda is None:
            continue
        indice = fernandez_huerta(o.texto)
        if indice is None:
            continue
        minimo = LEGIBILIDAD_MINIMA[banda]
        if indice < minimo:
            hallazgos.append(
                Hallazgo(
                    regla=11,
                    codigo_regla="R11_POCO_LEGIBLE",
                    severidad=Severidad.ADVERTENCIA,
                    objetivo=o.codigo,
                    mensaje=(
                        f"legibilidad {indice:.0f} para nivel '{o.nivel}' "
                        f"(mínimo esperado {minimo:.0f})"
                    ),
                    reparacion=(
                        f"Reescribe el texto de '{o.codigo}' con frases más cortas y "
                        "palabras más simples, **sin cambiar lo que el objetivo exige**. "
                        "Conserva el texto oficial en `fuente` para trazabilidad."
                    ),
                    datos={
                        "objetivo": o.codigo,
                        "indice": round(indice, 1),
                        "minimo": minimo,
                    },
                )
            )
    return hallazgos


def _r12_version(c: Curriculum) -> list[Hallazgo]:
    """Sin versión y vigencia no se puede fijar el currículo por estudiante."""
    hallazgos = []
    if not c.version or not c.version.strip():
        hallazgos.append(
            Hallazgo(
                regla=12,
                codigo_regla="R12_SIN_VERSION",
                severidad=Severidad.BLOQUEANTE,
                mensaje="el currículo no declara versión",
                reparacion=(
                    "Añade `version` con la fecha o identificador de la publicación "
                    "oficial de la que se importó."
                ),
                datos={},
            )
        )
    if c.vigencia_desde is None:
        hallazgos.append(
            Hallazgo(
                regla=12,
                codigo_regla="R12_SIN_VIGENCIA",
                severidad=Severidad.ADVERTENCIA,
                mensaje="el currículo no declara fecha de vigencia",
                reparacion="Añade `vigencia_desde` con la fecha de entrada en vigor.",
                datos={},
            )
        )
    return hallazgos


_REGLAS = (
    _r01_aciclico,
    _r02_prerequisitos_existen,
    _r03_sin_huerfanos,
    _r04_tiene_evaluacion,
    _r05_trazabilidad,
    _r06_cobertura_temario,
    _r07_horas_cuadran,
    _r08_sin_duplicados,
    _r09_profundidad,
    _r10_licencia,
    _r11_legibilidad,
    _r12_version,
)


def validar(curriculum: Curriculum) -> Resultado:
    """Corre las 12 reglas y devuelve todos los hallazgos.

    No se detiene en el primer error: el bucle de auto-reparación necesita la
    lista completa para arreglar en tandas en vez de una vuelta por fallo.
    """
    hallazgos: list[Hallazgo] = []
    for regla in _REGLAS:
        hallazgos.extend(regla(curriculum))
    return Resultado(hallazgos=hallazgos)
