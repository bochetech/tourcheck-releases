"""Los tres pases globales: lo que no se puede sacar mirando un trozo.

La extracción trabaja trozo a trozo y por eso no puede producir nada que dependa
del documento entero. Faltan tres cosas, y ninguna es opcional:

1. **Prerrequisitos.** Es el razonamiento más duro del pipeline y **lo que ningún
   ministerio publica**: las Bases Curriculares dan una lista, no un grafo. Sin
   grafo no hay secuencia, y sin secuencia no hay aprendizaje para dominio. Los
   errores los atrapan las reglas 1, 2 y 9, y los cierra el bucle de reparación.
2. **Resúmenes.** Son el índice RAG. Se escriben una vez y se leen en cada turno
   durante años: es la pieza que mantiene el contexto recuperado por debajo del
   presupuesto y evita indexar el PDF crudo.
3. **Ítems.** Al menos uno por objetivo, que es lo que exige la regla 4. Un
   objetivo que no se puede evaluar no se puede dar por dominado.

Cada pase devuelve una **copia** del currículo. Ninguno muta el que recibe: si un
pase sale mal, se descarta entero y el anterior sigue en pie.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from aula.curriculum.model import Curriculum, Objetivo
from aula.importador.extraccion import _cerrar
from aula.llm.cliente import Cliente, ErrorLLM

#: Cuántos objetivos entran en una llamada de prerrequisitos. Un nivel y
#: asignatura completos rondan los 40-60, y el pase necesita verlos todos juntos:
#: trocear aquí es justamente lo que se quiere evitar.
MAX_POR_GRAFO = 60

#: Los resúmenes y los ítems sí van por lotes: son independientes entre sí, y
#: lotes chicos dan respuestas más limpias en modelos pequeños.
LOTE_RESUMENES = 8
LOTE_ITEMS = 6

PALABRAS_RESUMEN = 100


class Informe(BaseModel):
    """Qué hizo un pase y qué se le rechazó. Lo mira una persona, una vez."""

    pase: str
    aplicados: int = 0
    rechazados: list[str] = Field(default_factory=list)
    errores: list[str] = Field(default_factory=list)
    pendientes: list[str] = Field(default_factory=list)

    def __str__(self) -> str:  # pragma: no cover - conveniencia
        return (
            f"{self.pase}: {self.aplicados} aplicados, "
            f"{len(self.rechazados)} rechazados, {len(self.pendientes)} sin cubrir"
        )


def _esquema(modelo: type[BaseModel]) -> dict[str, Any]:
    esquema = modelo.model_json_schema()
    _cerrar(esquema)
    return esquema


def _pedir(cliente: Cliente, sistema: str, contenido: str, modelo: type[BaseModel],
           nombre: str) -> Any:
    return cliente.completar(
        [{"role": "system", "content": sistema}, {"role": "user", "content": contenido}],
        esquema=_esquema(modelo),
        nombre_esquema=nombre,
    ).json_()


# ---------------------------------------------------------------------------
# 1. Prerrequisitos
# ---------------------------------------------------------------------------

INSTRUCCIONES_PREREQUISITOS = """Ordenas objetivos de aprendizaje por dependencia.

Te doy los objetivos de una asignatura y nivel. Devuelve las aristas "para
aprender A hay que dominar antes B".

Reglas:
- Solo prerrequisitos INMEDIATOS y necesarios. Si A necesita B y B necesita C,
  no declares que A necesita C: ya se deduce.
- Usa únicamente los códigos que te doy. No inventes ninguno.
- Un objetivo puede no tener prerrequisitos. La mayoría tiene cero o uno.
- Ante la duda, no declares la arista. Un prerrequisito de más bloquea a un niño
  en algo que ya podía hacer; uno de menos solo lo hace trabajar un poco a ciegas."""


class Arista(BaseModel):
    objetivo: str
    requiere: str


class Aristas(BaseModel):
    aristas: list[Arista] = Field(default_factory=list)


def pase_prerequisitos(
    curriculo: Curriculum, cliente: Cliente, al_avanzar=None
) -> tuple[Curriculum, Informe]:
    """Infiere el grafo de dependencias, por asignatura y nivel."""
    informe = Informe(pase="prerrequisitos")
    nuevo = curriculo.model_copy(deep=True)
    indice = nuevo.por_codigo()

    hechos = 0
    grupos: dict[tuple[str, str], list[Objetivo]] = {}
    for o in nuevo.objetivos:
        grupos.setdefault((o.nivel, o.asignatura), []).append(o)

    for (nivel, asignatura), objetivos in sorted(grupos.items()):
        for tanda in _en_tandas(objetivos, MAX_POR_GRAFO):
            codigos = {o.codigo for o in tanda}
            listado = "\n".join(f"{o.codigo}: {o.texto}" for o in tanda)
            try:
                crudo = _pedir(
                    cliente,
                    INSTRUCCIONES_PREREQUISITOS,
                    f"Asignatura {asignatura}, nivel {nivel}.\n\n{listado}",
                    Aristas,
                    "prerrequisitos",
                )
            except ErrorLLM as exc:
                informe.errores.append(f"{asignatura}/{nivel}: {exc}")
                continue

            for arista in _aristas_validas(crudo, codigos, indice, informe):
                indice[arista.objetivo].prerequisitos.append(arista.requiere)
                informe.aplicados += 1
            hechos += len(tanda)
            if al_avanzar is not None:
                al_avanzar("prerrequisitos", hechos, len(nuevo.objetivos))

    return nuevo, informe


def _aristas_validas(crudo: Any, codigos: set[str], indice: dict[str, Objetivo],
                     informe: Informe):
    """Acepta arista por arista, comprobando lo que el validador comprobaría después.

    Podríamos dejar pasar todo y que las reglas 1 y 2 lo canten. No se hace: un
    ciclo detectado aquí se descarta con una línea, y detectado después obliga al
    bucle de reparación a gastar una vuelta entera de modelo en deshacerlo.
    """
    if isinstance(crudo, list):
        crudo = {"aristas": crudo}
    if not isinstance(crudo, dict):
        informe.errores.append("la respuesta no tiene la forma esperada")
        return

    for entrada in crudo.get("aristas") or []:
        try:
            arista = Arista.model_validate(entrada)
        except ValidationError:
            informe.rechazados.append(f"arista mal formada: {entrada}")
            continue
        if arista.objetivo not in codigos or arista.requiere not in codigos:
            informe.rechazados.append(
                f"{arista.objetivo} ← {arista.requiere}: código fuera de la tanda"
            )
            continue
        if arista.objetivo == arista.requiere:
            informe.rechazados.append(f"{arista.objetivo}: se requiere a sí mismo")
            continue
        if arista.requiere in indice[arista.objetivo].prerequisitos:
            continue
        if _alcanza(arista.requiere, arista.objetivo, indice):
            informe.rechazados.append(
                f"{arista.objetivo} ← {arista.requiere}: cerraría un ciclo"
            )
            continue
        yield arista


def _alcanza(desde: str, hasta: str, indice: dict[str, Objetivo]) -> bool:
    """¿Se llega de `desde` a `hasta` siguiendo prerrequisitos ya aceptados?"""
    pila, vistos = [desde], set()
    while pila:
        actual = pila.pop()
        if actual == hasta:
            return True
        if actual in vistos or actual not in indice:
            continue
        vistos.add(actual)
        pila.extend(indice[actual].prerequisitos)
    return False


# ---------------------------------------------------------------------------
# 2. Resúmenes (el índice RAG)
# ---------------------------------------------------------------------------

INSTRUCCIONES_RESUMEN = f"""Escribes el resumen con el que se busca un objetivo
de aprendizaje en un índice.

Para cada objetivo, unas {PALABRAS_RESUMEN} palabras densas que digan qué
contenido cubre, con qué vocabulario y qué sabe hacer un niño que lo domina.

Reglas:
- Sin relleno, sin "este objetivo busca que el estudiante". Directo al contenido.
- Incluye las palabras que alguien usaría para buscarlo: los términos concretos
  de la materia.
- No inventes contenido que no esté en el texto del objetivo.
- Devuelve el código exactamente como te lo doy."""


class ResumenDe(BaseModel):
    codigo: str
    resumen: str


class Resumenes(BaseModel):
    resumenes: list[ResumenDe] = Field(default_factory=list)


def pase_resumenes(
    curriculo: Curriculum, cliente: Cliente, al_avanzar=None
) -> tuple[Curriculum, Informe]:
    """Escribe el resumen denso de cada objetivo: el índice que se leerá siempre."""
    informe = Informe(pase="resumenes")
    nuevo = curriculo.model_copy(deep=True)
    indice = nuevo.por_codigo()
    faltan = [o for o in nuevo.objetivos if not o.resumen]
    hechos = 0

    for tanda in _en_tandas(faltan, LOTE_RESUMENES):
        listado = "\n".join(f"{o.codigo}: {o.texto}" for o in tanda)
        try:
            crudo = _pedir(cliente, INSTRUCCIONES_RESUMEN, listado, Resumenes, "resumenes")
        except ErrorLLM as exc:
            informe.errores.append(str(exc))
            continue
        for entrada in _lista(crudo, "resumenes", informe):
            try:
                item = ResumenDe.model_validate(entrada)
            except ValidationError:
                informe.rechazados.append(f"resumen mal formado: {entrada}")
                continue
            if item.codigo not in indice or not item.resumen.strip():
                informe.rechazados.append(f"{item.codigo}: código desconocido o vacío")
                continue
            indice[item.codigo].resumen = " ".join(item.resumen.split())
            informe.aplicados += 1
        hechos += len(tanda)
        if al_avanzar is not None:
            al_avanzar("resumenes", hechos, len(faltan))

    informe.pendientes = [o.codigo for o in nuevo.objetivos if not o.resumen]
    return nuevo, informe


# ---------------------------------------------------------------------------
# 3. Ítems de evaluación
# ---------------------------------------------------------------------------

INSTRUCCIONES_ITEMS = """Escribes preguntas para comprobar si un niño domina un
objetivo de aprendizaje.

Para cada objetivo, 2 o 3 preguntas breves, en español de Chile, de dificultad
creciente.

Reglas:
- La primera comprueba lo básico del objetivo; la última, si lo sabe aplicar.
- Preguntas concretas y respondibles, no consignas de actividad.
- Nada de "explica la importancia de". Que se pueda saber si está bien o mal.
- Devuelve el código exactamente como te lo doy."""


class ItemsDe(BaseModel):
    codigo: str
    items: list[str] = Field(default_factory=list)


class Items(BaseModel):
    items: list[ItemsDe] = Field(default_factory=list)


def pase_items(
    curriculo: Curriculum, cliente: Cliente, al_avanzar=None
) -> tuple[Curriculum, Informe]:
    """Al menos un ítem por objetivo: es lo que exige la regla 4."""
    informe = Informe(pase="items")
    nuevo = curriculo.model_copy(deep=True)
    indice = nuevo.por_codigo()
    faltan = [o for o in nuevo.objetivos if not o.items]
    hechos = 0

    for tanda in _en_tandas(faltan, LOTE_ITEMS):
        listado = "\n".join(f"{o.codigo}: {o.texto}" for o in tanda)
        try:
            crudo = _pedir(cliente, INSTRUCCIONES_ITEMS, listado, Items, "items")
        except ErrorLLM as exc:
            informe.errores.append(str(exc))
            continue
        for entrada in _lista(crudo, "items", informe):
            try:
                item = ItemsDe.model_validate(entrada)
            except ValidationError:
                informe.rechazados.append(f"ítems mal formados: {entrada}")
                continue
            limpios = [" ".join(t.split()) for t in item.items if t.strip()]
            if item.codigo not in indice or not limpios:
                informe.rechazados.append(f"{item.codigo}: código desconocido o sin ítems")
                continue
            indice[item.codigo].items = limpios
            informe.aplicados += 1
        hechos += len(tanda)
        if al_avanzar is not None:
            al_avanzar("items", hechos, len(faltan))

    informe.pendientes = [o.codigo for o in nuevo.objetivos if not o.items]
    return nuevo, informe


# ---------------------------------------------------------------------------


def _lista(crudo: Any, clave: str, informe: Informe) -> list:
    if isinstance(crudo, list):
        return crudo
    if not isinstance(crudo, dict):
        informe.errores.append("la respuesta no tiene la forma esperada")
        return []
    return crudo.get(clave) or []


def _en_tandas(elementos: list, tamano: int):
    for i in range(0, len(elementos), tamano):
        yield elementos[i : i + tamano]


def enriquecer(
    curriculo: Curriculum,
    cliente_enriquecimiento: Cliente,
    cliente_resumen: Cliente,
    cliente_items: Cliente,
    al_avanzar=None,
) -> tuple[Curriculum, list[Informe]]:
    """Los tres pases en orden, cada uno con el modelo que le toca.

    El orden no es casual: los prerrequisitos necesitan el texto original limpio,
    y los ítems salen mejor cuando el objetivo ya tiene resumen.
    """
    informes = []
    curriculo, inf = pase_prerequisitos(curriculo, cliente_enriquecimiento, al_avanzar)
    informes.append(inf)
    curriculo, inf = pase_resumenes(curriculo, cliente_resumen, al_avanzar)
    informes.append(inf)
    curriculo, inf = pase_items(curriculo, cliente_items, al_avanzar)
    informes.append(inf)
    return curriculo, informes
