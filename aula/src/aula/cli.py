"""CLI de Aula.

Expone las cuatro cosas que hoy existen: el importador de currículo, el
validador, el bucle de auto-reparación y la configuración de modelos y familia.

El importador está partido en `fetch` (necesita red, se corre una vez) y
`extract` (sin red, se corre las veces que haga falta) porque son trabajos
distintos: descargar necesita permiso de salida, y entender necesita iterar. La
caché de `datos/fuentes/` es lo que los une, y es portátil a propósito.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from aula.config import ROLES_CARA_AL_NINO, Rol, cargar_config
from aula.familia import (
    Adulto,
    Asignacion,
    Estudiante,
    Familia,
    ModoUI,
    cargar_familia,
    guardar_familia,
)
from aula.curriculum.proponente import ProponenteConModelo
from aula.curriculum.reparador import reparar
from aula.llm.cliente import ErrorLLM, para_rol
from aula.curriculum.io import cargar, guardar
from aula.importador import catalogo as cat
from aula.importador import descarga as desc
from aula.importador.codigos import IndiceCodigos
from aula.importador.pipeline import importar, leer_de_cache
from aula.importador.texto import SinCapaDeTexto
from aula.importador.trozos import trocear
from aula.curriculum.validator import Severidad, validar

app = typer.Typer(help="Aula — tutoría con IA anclada a un currículo validado.")
curriculum_app = typer.Typer(help="Importar, validar y versionar planes de estudio.")
config_app = typer.Typer(help="Ver y comprobar la configuración de modelos.")
app.add_typer(curriculum_app, name="curriculum")
familia_app = typer.Typer(help="Familia, estudiantes y sus planes de estudio.")
app.add_typer(config_app, name="config")
app.add_typer(familia_app, name="familia")

console = Console()
err_console = Console(stderr=True)


@curriculum_app.command("validate")
def validate(
    archivo: Path = typer.Argument(..., help="Currículo en YAML."),
    formato_json: bool = typer.Option(
        False, "--json", help="Salida legible por máquina, para el bucle de reparación."
    ),
) -> None:
    """Corre las 12 reglas duras sobre un plan de estudios."""
    try:
        curriculo = cargar(archivo)
    except Exception as exc:  # noqa: BLE001 - el usuario necesita el motivo tal cual
        err_console.print(f"[red]No se pudo cargar {archivo}:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    resultado = validar(curriculo)

    if formato_json:
        salida = {
            "curriculum": curriculo.id,
            "version": curriculo.version,
            "objetivos": len(curriculo.objetivos),
            "ok": resultado.ok,
            "hallazgos": [h.model_dump(mode="json") for h in resultado.hallazgos],
        }
        console.print_json(json.dumps(salida, ensure_ascii=False))
        raise typer.Exit(code=0 if resultado.ok else 1)

    console.print(
        f"[bold]{curriculo.id}[/bold] v{curriculo.version} — "
        f"{len(curriculo.objetivos)} objetivos"
    )

    if not resultado.hallazgos:
        console.print("[green]Las 12 reglas pasan. El plan es utilizable.[/green]")
        raise typer.Exit(code=0)

    tabla = Table(show_lines=False, header_style="bold")
    tabla.add_column("Regla", width=6)
    tabla.add_column("Sev", width=12)
    tabla.add_column("Objetivo", width=14, overflow="fold")
    tabla.add_column("Problema", overflow="fold")
    for h in resultado.hallazgos:
        color = "red" if h.severidad is Severidad.BLOQUEANTE else "yellow"
        tabla.add_row(
            f"R{h.regla:02d}",
            f"[{color}]{h.severidad.value}[/{color}]",
            h.objetivo or "—",
            h.mensaje,
        )
    console.print(tabla)

    n_bloq, n_adv = len(resultado.bloqueantes), len(resultado.advertencias)
    adv = f"{n_adv} advertencia" + ("s" if n_adv != 1 else "")
    bloq = f"{n_bloq} bloqueante" + ("s" if n_bloq != 1 else "")
    if resultado.ok:
        console.print(
            f"[green]Utilizable[/green] — 0 bloqueantes, {adv}. "
            "Las advertencias van a la cola de excepciones, no frenan el arranque."
        )
    else:
        console.print(
            f"[red]No utilizable[/red] — {bloq}, {adv}. "
            "Cada hallazgo trae su instrucción de reparación: usa --json para el bucle."
        )
    raise typer.Exit(code=0 if resultado.ok else 1)


@config_app.command("show")
def config_show(
    perfil: str = typer.Option(None, "--perfil", "-p", help="Perfil a inspeccionar."),
) -> None:
    """Muestra qué modelo usa cada rol y avisa de lo que va a fallar o costar."""
    try:
        config = cargar_config(perfil=perfil)
    except (KeyError, OSError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    console.print()
    console.print(f"  Perfil activo  [bold cyan]{config.perfil}[/bold cyan]")
    console.print()

    tabla = Table(
        box=box.SIMPLE_HEAD,
        header_style="bold dim",
        padding=(0, 1),
        show_edge=False,
        pad_edge=False,
    )
    tabla.add_column("  Rol", width=19, no_wrap=True)
    tabla.add_column("Dónde", width=5, no_wrap=True)
    tabla.add_column("Modelo", width=26, no_wrap=True, overflow="ellipsis")
    tabla.add_column("Salida", width=7, justify="right", no_wrap=True)
    tabla.add_column("Contexto", width=8, justify="right", no_wrap=True)

    for rol in Rol:
        if rol not in config.roles:
            continue
        cfg = config.para(rol)
        prov = config.proveedores.get(cfg.proveedor)
        local = prov is not None and not prov.base_url.startswith("https://")
        marca = "[cyan]•[/cyan]" if rol in ROLES_CARA_AL_NINO else " "
        tabla.add_row(
            f"  {marca} {rol.value}",
            "[green]local[/green]" if local else "[yellow]nube[/yellow]",
            f"[dim]{cfg.proveedor}[/dim] {cfg.modelo}",
            f"{cfg.max_tokens:,}",
            f"{cfg.presupuesto_contexto:,}" if cfg.presupuesto_contexto else "[dim]—[/dim]",
        )

    console.print(tabla)
    console.print("  [dim][cyan]•[/cyan] el niño interactúa con este rol en vivo[/dim]")
    console.print()

    avisos = config.revisar()
    if not avisos:
        console.print("  [green]Configuración coherente.[/green]")
        console.print()
        raise typer.Exit(code=0)

    for aviso in avisos:
        color = "red" if aviso.grave else "yellow"
        etiqueta = "error" if aviso.grave else "aviso"
        donde = f" {aviso.rol.value}" if aviso.rol else ""
        console.print(f"  [{color}]{etiqueta}[/{color}]{donde} — {aviso.mensaje}")
    console.print()
    raise typer.Exit(code=1 if any(a.grave for a in avisos) else 0)


@config_app.command("probe")
def config_probe(
    perfil: str = typer.Option(None, "--perfil", "-p", help="Perfil a probar."),
) -> None:
    """Comprueba que cada proveedor responde y muestra qué modelos tiene cargados."""
    try:
        config = cargar_config(perfil=perfil)
    except (KeyError, OSError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    usados = {config.para(rol).proveedor for rol in Rol if rol in config.roles}
    console.print()
    console.print(f"  Perfil  [bold cyan]{config.perfil}[/bold cyan]")
    console.print()

    problemas = 0
    for pid in sorted(usados):
        prov = config.proveedores[pid]
        console.print(f"  [bold]{pid}[/bold]  [dim]{prov.base_url}[/dim]")
        rol_cualquiera = next(r for r in Rol if r in config.roles and config.para(r).proveedor == pid)
        try:
            modelos = para_rol(config, rol_cualquiera).modelos_disponibles()
        except ErrorLLM as exc:
            problemas += 1
            console.print(f"    [red]sin respuesta[/red] — {exc}")
            console.print()
            continue
        if not modelos:
            problemas += 1
            console.print("    [yellow]responde, pero no hay ningún modelo cargado[/yellow]")
        for m in modelos[:8]:
            console.print(f"    [green]•[/green] {m}")
        if len(modelos) > 8:
            console.print(f"    [dim]… y {len(modelos) - 8} más[/dim]")
        console.print()

    if problemas:
        console.print(
            "  [dim]Un proveedor local que no responde suele ser el servidor apagado, "
            "o 127.0.0.1 desde dentro de un contenedor: prueba "
            "AULA_HOST_LLM=host.docker.internal[/dim]"
        )
        console.print()
    raise typer.Exit(code=1 if problemas else 0)


def _cargar_o_avisar(ruta: Path | None):
    try:
        return cargar_familia(ruta)
    except (FileNotFoundError, ValueError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc


@familia_app.command("crear")
def familia_crear(
    nombre: str = typer.Argument(..., help="Cómo se llama la familia."),
    adulto: list[str] = typer.Option([], "--adulto", "-a", help="Adulto que acompaña."),
    pais: str = typer.Option("CL", "--pais", help="Decide el currículo por defecto."),
    ruta: Path = typer.Option(None, "--ruta", help="Dónde guardarla."),
) -> None:
    """Crea la familia. Una instalación, una familia."""
    familia = Familia(nombre=nombre, pais=pais)
    for quien in adulto:
        familia.agregar_adulto(Adulto(nombre=quien))
    destino = guardar_familia(familia, ruta)
    console.print(f"  [green]Familia «{familia.nombre}» creada[/green] [dim]{destino}[/dim]")


@familia_app.command("agregar")
def familia_agregar(
    nombre: str = typer.Argument(..., help="Nombre del niño o niña."),
    nacimiento: str = typer.Option(..., "--nacimiento", "-n", help="AAAA-MM-DD."),
    modo: ModoUI = typer.Option(None, "--modo", help="Fuerza la piel; por defecto va por edad."),
    companero: str = typer.Option("Copi", "--companero", help="Cómo llama al compañero."),
    presupuesto: float = typer.Option(4.0, "--presupuesto", help="Tope mensual en USD."),
    ruta: Path = typer.Option(None, "--ruta"),
) -> None:
    """Agrega un estudiante. El nombre del compañero debería ponérselo el niño."""
    familia = _cargar_o_avisar(ruta)
    try:
        estudiante = familia.agregar_estudiante(Estudiante(
            nombre=nombre,
            nacimiento=dt.date.fromisoformat(nacimiento),
            modo_ui=modo,
            nombre_companero=companero,
            presupuesto_mensual_usd=presupuesto,
        ))
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    guardar_familia(familia, ruta)
    console.print(
        f"  [green]{estudiante.nombre} agregado[/green] — {estudiante.edad()} años, "
        f"modo {estudiante.modo_efectivo().value}, voz {estudiante.voz_efectiva().value}"
    )


@familia_app.command("asignar")
def familia_asignar(
    estudiante: str = typer.Argument(..., help="Nombre o id del estudiante."),
    curriculo: str = typer.Option(..., "--curriculo", "-c", help="Id del currículo."),
    version: str = typer.Option(..., "--version", "-v", help="Versión, que queda fijada."),
    nivel: str = typer.Option(..., "--nivel", "-n", help="Curso, por ejemplo 02."),
    nota: str = typer.Option("", "--nota", help="Por qué se asigna o se migra."),
    ruta: Path = typer.Option(None, "--ruta"),
) -> None:
    """Asigna un plan de estudios, fijado a una versión concreta."""
    familia = _cargar_o_avisar(ruta)
    try:
        quien = familia.estudiante(estudiante)
        anterior = quien.asignacion
        quien.asignar(Asignacion(
            curriculum_id=curriculo, version=version, nivel=nivel, nota=nota))
    except (KeyError, ValueError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    guardar_familia(familia, ruta)
    if anterior is not None:
        console.print(
            f"  [yellow]{quien.nombre} migrado[/yellow] de "
            f"{anterior.curriculum_id}@{anterior.version} nivel {anterior.nivel} "
            f"a {curriculo}@{version} nivel {nivel}"
        )
        console.print("  [dim]La asignación anterior queda en el historial.[/dim]")
    else:
        console.print(
            f"  [green]{quien.nombre} → {curriculo}@{version}, nivel {nivel}[/green]"
        )


@familia_app.command("mostrar")
def familia_mostrar(ruta: Path = typer.Option(None, "--ruta")) -> None:
    """Muestra quién hay en la familia y qué plan tiene cada uno."""
    familia = _cargar_o_avisar(ruta)

    console.print()
    console.print(f"  [bold]{familia.nombre}[/bold]  [dim]{familia.pais}[/dim]")
    if familia.adultos:
        console.print(f"  [dim]acompañan: {', '.join(a.nombre for a in familia.adultos)}[/dim]")
    console.print()

    if not familia.estudiantes:
        console.print("  [dim]Sin estudiantes todavía: `aula familia agregar`[/dim]")
        console.print()
        raise typer.Exit(code=0)

    tabla = Table(box=box.SIMPLE_HEAD, header_style="bold dim", padding=(0, 1),
                  show_edge=False, pad_edge=False)
    tabla.add_column("  Estudiante", width=14, no_wrap=True)
    tabla.add_column("Edad", width=4, justify="right")
    tabla.add_column("Modo", width=11, no_wrap=True)
    tabla.add_column("Plan asignado", width=30, no_wrap=True, overflow="ellipsis")
    tabla.add_column("Tope", width=6, justify="right")

    for e in familia.estudiantes:
        plan = (
            f"{e.asignacion.curriculum_id}@{e.asignacion.version} · {e.asignacion.nivel}"
            if e.asignacion else "[yellow]sin asignar[/yellow]"
        )
        tabla.add_row(
            f"  {e.nombre}", str(e.edad()), e.modo_efectivo().value, plan,
            f"${e.presupuesto_mensual_usd:g}",
        )
    console.print(tabla)
    console.print()
    for e in familia.estudiantes:
        console.print(
            f"  [dim]{e.nombre}: voz {e.voz_efectiva().value}, "
            f"compañero «{e.nombre_companero}»[/dim]"
        )
    console.print(f"  [dim]tope conjunto: US${familia.presupuesto_total_usd:g}/mes[/dim]")
    console.print()


ESQUEMA_PRUEBA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "capital": {"type": "string"},
        "habitantes_millones": {"type": "number"},
        "es_isla": {"type": "boolean"},
    },
    "required": ["capital", "habitantes_millones", "es_isla"],
}


@config_app.command("test")
def config_test(
    rol: Rol = typer.Option(Rol.TUTOR, "--rol", "-r", help="Qué rol probar."),
    todos: bool = typer.Option(False, "--todos", help="Prueba todos los roles."),
    perfil: str = typer.Option(None, "--perfil", "-p"),
) -> None:
    """Comprueba que el modelo respeta un esquema JSON.

    Es el supuesto que sostiene todo el diseño local: el vocabulario cerrado de
    reparación depende de que el servidor obligue al modelo a producir algo con
    la forma correcta. Si un modelo no lo respeta, hay que saberlo antes de
    construir encima, no después.
    """
    try:
        config = cargar_config(perfil=perfil)
    except (KeyError, OSError, FileNotFoundError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    roles = [r for r in Rol if r in config.roles] if todos else [rol]
    roles = [r for r in roles if r is not Rol.EMBEDDINGS]

    console.print()
    fallos = 0
    for r in roles:
        cfg = config.para(r)
        console.print(f"  [bold]{r.value}[/bold]  [dim]{cfg.modelo}[/dim]")
        inicio = time.monotonic()
        try:
            cliente_prueba = para_rol(config, r)
            # El tope del tutor está pensado para respuestas de 2-3 frases; para
            # un diagnóstico conviene dar aire y no confundir corte con fallo.
            cliente_prueba.modelo = cliente_prueba.modelo.model_copy(
                update={"max_tokens": max(cliente_prueba.modelo.max_tokens, 512)}
            )
            respuesta = cliente_prueba.completar(
                [
                    {"role": "system", "content": "Responde solo con el JSON pedido."},
                    {"role": "user", "content": "Datos de Chile."},
                ],
                esquema=ESQUEMA_PRUEBA,
                nombre_esquema="pais",
            )
            datos = respuesta.json_()
        except ErrorLLM as exc:
            fallos += 1
            console.print(f"    [red]falló[/red] — {exc}")
            console.print()
            continue

        segundos = time.monotonic() - inicio
        faltan = [c for c in ESQUEMA_PRUEBA["required"] if c not in datos]
        sobran = [c for c in datos if c not in ESQUEMA_PRUEBA["properties"]]

        if faltan or sobran or not isinstance(datos.get("es_isla"), bool):
            fallos += 1
            console.print(f"    [red]no respeta el esquema[/red] — devolvió {datos}")
            console.print(
                "    [dim]Sin decodificación restringida, el vocabulario cerrado "
                "de reparación no se sostiene con este modelo.[/dim]"
            )
        else:
            console.print(f"    [green]respeta el esquema[/green] — {datos}")
        console.print(f"    [dim]{segundos:.1f} s · {respuesta.tokens_salida} tokens[/dim]")
        console.print()

    if fallos:
        console.print(f"  [red]{fallos} de {len(roles)} fallaron.[/red]")
        console.print()
    raise typer.Exit(code=1 if fallos else 0)


@curriculum_app.command("reparar")
def curriculum_reparar(
    archivo: Path = typer.Argument(..., help="Currículo en YAML."),
    salida: Path = typer.Option(None, "--salida", "-o", help="Dónde escribir el reparado."),
    vueltas: int = typer.Option(4, "--vueltas", help="Tope de iteraciones."),
    perfil: str = typer.Option(None, "--perfil", "-p"),
) -> None:
    """Deja que el modelo cierre solo lo que el validador encontró.

    Solo llega a ti lo que la máquina no supo cerrar.
    """
    try:
        curriculo = cargar(archivo)
        config = cargar_config(perfil=perfil)
    except (KeyError, OSError, FileNotFoundError, ValueError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    cliente = para_rol(config, Rol.ENRIQUECIMIENTO)
    proponente = ProponenteConModelo(cliente, permitir_agregado=False)

    console.print()
    console.print(
        f"  [bold]{curriculo.id}[/bold] v{curriculo.version} — "
        f"{len(curriculo.objetivos)} objetivos"
    )
    console.print(f"  [dim]reparando con {cliente.modelo.modelo}[/dim]")
    console.print()

    def contar(vuelta) -> None:
        aplicadas = sum(1 for a in vuelta.aplicaciones if a.aplicada)
        estado = "[green]adoptada[/green]" if vuelta.adoptada else "[yellow]descartada[/yellow]"
        console.print(
            f"  vuelta {vuelta.numero}: {vuelta.bloqueantes_antes} → "
            f"{vuelta.bloqueantes_despues} bloqueantes, "
            f"{aplicadas}/{len(vuelta.aplicaciones)} operaciones · {estado}"
        )
        if not vuelta.adoptada:
            console.print(f"  [dim]{vuelta.motivo}[/dim]")

    reparado, reparacion = reparar(curriculo, proponente, max_vueltas=vueltas, al_avanzar=contar)

    console.print()
    if proponente.ultimo_error:
        console.print(f"  [yellow]aviso del modelo:[/yellow] {proponente.ultimo_error}")
    console.print(f"  {reparacion.resumen()}")

    pendientes = reparacion.pendientes_para_el_padre
    if pendientes:
        console.print()
        console.print("  [bold]Para que lo mires tú:[/bold]")
        for h in pendientes[:12]:
            color = "red" if h.severidad is Severidad.BLOQUEANTE else "yellow"
            donde = f" [dim]{h.objetivo}[/dim]" if h.objetivo else ""
            console.print(f"    [{color}]•[/{color}]{donde} {h.mensaje}")
        if len(pendientes) > 12:
            console.print(f"    [dim]… y {len(pendientes) - 12} más[/dim]")

    destino = salida or archivo.with_name(archivo.stem + ".reparado.yaml")
    guardar(reparado, destino)
    console.print()
    console.print(f"  [green]escrito[/green] [dim]{destino}[/dim]")
    console.print()
    raise typer.Exit(code=0 if reparacion.ok else 1)


# ---------------------------------------------------------------------------
# Importador
# ---------------------------------------------------------------------------


@curriculum_app.command("fetch")
def curriculum_fetch(
    pais: str = typer.Option("CL", "--pais", help="País del catálogo."),
    nivel: str = typer.Option(None, "--nivel", help='Nivel, p. ej. "02".'),
    asignatura: str = typer.Option(None, "--asignatura", help='Sigla, p. ej. "MA".'),
    ids: list[str] = typer.Option(None, "--id", help="Documento concreto del catálogo."),
    cache: Path = typer.Option(desc.CACHE_POR_DEFECTO, "--cache", help="Dónde guardar."),
    forzar: bool = typer.Option(False, "--forzar", help="Volver a descargar."),
    todos: bool = typer.Option(False, "--todos", help="Incluir los inactivos."),
) -> None:
    """Descarga documentos oficiales a la caché: la única etapa que usa red."""
    try:
        docs = cat.documentos(
            pais,
            nivel=nivel,
            asignatura=asignatura,
            clase=None,
            ids=list(ids) if ids else None,
            incluir_inactivos=todos,
        )
    except KeyError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    if not docs:
        err_console.print("[yellow]Ningún documento del catálogo cuadra con el filtro.[/yellow]")
        raise typer.Exit(code=2)

    console.print()
    console.print(f"  Trayendo {len(docs)} documento(s) a [dim]{cache}[/dim]")
    console.print()

    traidas, fallos = desc.traer_todos(docs, cache, forzar=forzar)
    for d in traidas:
        console.print(f"  [green]ok[/green]  {d.id}  [dim]{d.bytes:,} bytes[/dim]")
    for doc_id, motivo in fallos:
        console.print(f"  [red]no[/red]  {doc_id}  [dim]{motivo}[/dim]")

    console.print()
    console.print(
        f"  {len(traidas)} en caché, {len(fallos)} sin traer. "
        "Lo demás corre sin red."
    )
    console.print()
    raise typer.Exit(code=0 if traidas else 1)


@curriculum_app.command("adjuntar")
def curriculum_adjuntar(
    archivo: Path = typer.Argument(..., help="PDF o HTML que ya tienes en el disco."),
    doc_id: str = typer.Option(..., "--id", help="Identificador del documento."),
    pais: str = typer.Option("CL", "--pais"),
    titulo: str = typer.Option(None, "--titulo", help="Cómo se llamará en `fuente.doc`."),
    nivel: str = typer.Option(None, "--nivel"),
    asignatura: str = typer.Option(None, "--asignatura"),
    clase: str = typer.Option("programa", "--clase", help="temario|programa|bases|plan_horas|oa"),
    cache: Path = typer.Option(desc.CACHE_POR_DEFECTO, "--cache"),
) -> None:
    """Mete en la caché un documento que ya tienes bajado.

    Entra por el mismo camino que uno descargado: mismo manifiesto, mismo sha256,
    misma extracción. Es la vía para los documentos sin URL estable.
    """
    try:
        documento = cat.por_id(pais, doc_id)
        if titulo:
            documento = documento.model_copy(update={"titulo": titulo})
    except KeyError:
        # Un id fuera del catálogo es legítimo: alguien tiene un PDF que aún no
        # está declarado. Se le arma una ficha con la licencia conservadora.
        documento = cat.Documento(
            id=doc_id,
            tipo="pdf" if archivo.suffix.lower() == ".pdf" else "html",
            clase=clase,  # type: ignore[arg-type]
            titulo=titulo or doc_id,
            nivel=nivel,
            asignatura=asignatura,
        )

    try:
        descarga = desc.adjuntar(documento, archivo, cache)
    except desc.ErrorDescarga as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    console.print()
    console.print(f"  [green]adjuntado[/green] {descarga.id}  [dim]{descarga.bytes:,} bytes[/dim]")
    console.print(f"  [dim]{descarga.ruta(cache)} · sha256 {descarga.sha256[:12]}…[/dim]")
    console.print()
    console.print("  Ahora: [bold]aula curriculum inspeccionar[/bold] para ver qué hay dentro.")
    console.print()


def _plural(n: int, palabra: str) -> str:
    return f"{n} {palabra}" + ("s" if n != 1 else "")


@curriculum_app.command("inspeccionar")
def curriculum_inspeccionar(
    doc_id: str = typer.Option(None, "--id", help="Solo este documento."),
    cache: Path = typer.Option(desc.CACHE_POR_DEFECTO, "--cache"),
    listar: int = typer.Option(10, "--listar", help="Cuántos códigos mostrar."),
) -> None:
    """Mira qué hay en un documento de la caché, sin modelo y sin red.

    Es el primer diagnóstico y el más barato: si aquí no aparecen códigos, no hay
    nada que extraer y el problema está en el documento, no en el modelo. Correr
    esto antes de gastar media hora de GPU ahorra media hora de GPU.
    """
    manifiesto = desc.cargar_manifiesto(cache)
    entradas = [
        d for d in manifiesto.descargas.values() if doc_id is None or d.id == doc_id
    ]
    if not entradas:
        err_console.print(
            f"[yellow]No hay nada en {cache}.[/yellow] Corre `aula curriculum fetch` "
            "o `aula curriculum adjuntar`."
        )
        raise typer.Exit(code=2)

    problemas = desc.verificar(cache)
    if problemas:
        for p in problemas:
            err_console.print(f"  [red]caché dañada[/red] {p}")

    console.print()
    for entrada in entradas:
        try:
            doc = leer_de_cache(entrada, cache)
        except SinCapaDeTexto as exc:
            console.print(f"  [red]{entrada.id}[/red]  {exc}")
            continue
        except ImportError as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2) from exc

        indice = IndiceCodigos(doc)
        trozos = trocear(doc, indice)
        console.print(f"  [bold]{entrada.titulo or entrada.id}[/bold]")
        console.print(
            f"    {_plural(len(doc.paginas), 'página')} · "
            f"{len(doc.texto):,} caracteres · "
            f"{_plural(len(indice), 'código')} distinto"
            f"{'s' if len(indice) != 1 else ''} · "
            f"{_plural(len(trozos), 'trozo')}"
        )
        if not len(indice):
            console.print(
                "    [yellow]Ningún código de objetivo. O el documento no los trae, "
                "o el patrón no cuadra con este país.[/yellow]"
            )
        else:
            muestra = indice.codigos[:listar]
            console.print(f"    [dim]{', '.join(muestra)}"
                          + (f", … (+{len(indice) - len(muestra)})" if len(indice) > len(muestra) else "")
                          + "[/dim]")
            niveles = ", ".join(sorted(indice.niveles()))
            asigs = ", ".join(sorted(indice.asignaturas()))
            console.print(f"    [dim]niveles: {niveles} · asignaturas: {asigs}[/dim]")
        console.print()


@curriculum_app.command("extract")
def curriculum_extract(
    pais: str = typer.Option("CL", "--pais"),
    nivel: str = typer.Option(None, "--nivel"),
    asignatura: str = typer.Option(None, "--asignatura"),
    ids: list[str] = typer.Option(None, "--id"),
    cache: Path = typer.Option(desc.CACHE_POR_DEFECTO, "--cache"),
    salida: Path = typer.Option(None, "--salida", "-o", help="YAML de destino."),
    sin_pases: bool = typer.Option(
        False, "--sin-pases", help="Solo extraer: sin prerrequisitos, resúmenes ni ítems."
    ),
    perfil: str = typer.Option(None, "--perfil", "-p"),
) -> None:
    """Convierte la caché en un currículo canónico, sin tocar la red."""
    try:
        config = cargar_config(perfil=perfil)
    except (KeyError, OSError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    inicio = time.time()
    ultimo = {"etapa": ""}

    def avanzar(etapa: str, hecho: int, total: int) -> None:
        if etapa != ultimo["etapa"]:
            console.print(f"  [dim]{etapa}…[/dim]")
            ultimo["etapa"] = etapa
        if total and (hecho == total or hecho % 10 == 0):
            console.print(f"    {hecho}/{total}")

    try:
        curriculo, informe = importar(
            pais,
            config,
            nivel=nivel,
            asignatura=asignatura,
            ids=list(ids) if ids else None,
            cache=cache,
            con_pases=not sin_pases,
            al_avanzar=avanzar,
        )
    except (FileNotFoundError, KeyError, ImportError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    except ErrorLLM as exc:
        err_console.print(f"[red]el modelo falló:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    _informar_importacion(informe, time.time() - inicio)

    destino = salida or Path(f"{curriculo.id}.yaml")
    guardar(curriculo, destino)
    console.print(f"  [green]escrito[/green] [dim]{destino}[/dim]")
    console.print()
    console.print(
        "  Ahora: [bold]aula curriculum reparar "
        f"{destino}[/bold] para cerrar lo que el validador encuentre."
    )
    console.print()
    raise typer.Exit(code=0 if curriculo.objetivos else 1)


def _informar_importacion(informe, segundos: float) -> None:
    """Lo que hay que mirar después de importar, y nada más.

    La cobertura va primero porque es la única métrica honesta: el denominador lo
    calculó una expresión regular sobre el documento, no el modelo.
    """
    console.print()
    console.print(f"  {informe.resumen()}  [dim]{segundos:.0f}s[/dim]")
    for d in informe.documentos:
        console.print(f"  [dim]· {d}[/dim]")

    if informe.no_vistos:
        console.print()
        console.print(
            f"  [yellow]{len(informe.no_vistos)} códigos del documento que el modelo "
            f"no devolvió:[/yellow] [dim]{', '.join(informe.no_vistos[:8])}"
            + ("…" if len(informe.no_vistos) > 8 else "")
            + "[/dim]"
        )
    if informe.descartes:
        console.print()
        console.print(f"  [yellow]{len(informe.descartes)} descartes[/yellow]")
        for d in informe.descartes[:6]:
            console.print(f"    [dim]{d}[/dim]")
        if len(informe.descartes) > 6:
            console.print(f"    [dim]… y {len(informe.descartes) - 6} más[/dim]")
    if informe.dudosos:
        console.print()
        console.print(
            f"  [yellow]{len(informe.dudosos)} con confianza baja[/yellow], para mirar a "
            f"mano: [dim]{', '.join(informe.dudosos[:8])}[/dim]"
        )
    for inf in informe.informes_pases:
        console.print(f"  [dim]{inf}[/dim]")
    for e in informe.errores[:5]:
        console.print(f"  [red]{e}[/red]")
    console.print()


@curriculum_app.command("import")
def curriculum_import(
    pais: str = typer.Option("CL", "--pais"),
    nivel: str = typer.Option(None, "--nivel"),
    asignatura: str = typer.Option(None, "--asignatura"),
    cache: Path = typer.Option(desc.CACHE_POR_DEFECTO, "--cache"),
    salida: Path = typer.Option(None, "--salida", "-o"),
    vueltas: int = typer.Option(4, "--vueltas"),
    perfil: str = typer.Option(None, "--perfil", "-p"),
    sin_red: bool = typer.Option(False, "--sin-red", help="Saltarse el fetch."),
) -> None:
    """Todo seguido: descargar, extraer y reparar. Es el comando de un solo paso.

    El plan es que esto termine desatendido en menos de media hora. Si tarda más,
    la respuesta correcta es recortar el alcance, no acostumbrarse a esperar.
    """
    inicio = time.time()
    try:
        config = cargar_config(perfil=perfil)
    except (KeyError, OSError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    if not sin_red:
        docs = cat.documentos(pais, nivel=nivel, asignatura=asignatura)
        if docs:
            console.print()
            console.print(f"  [dim]trayendo {len(docs)} documento(s)…[/dim]")
            _, fallos = desc.traer_todos(docs, cache)
            for doc_id, motivo in fallos:
                console.print(f"  [yellow]sin traer[/yellow] {doc_id}: [dim]{motivo}[/dim]")

    try:
        curriculo, informe = importar(
            pais, config, nivel=nivel, asignatura=asignatura, cache=cache
        )
    except (FileNotFoundError, KeyError, ImportError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    except ErrorLLM as exc:
        err_console.print(f"[red]el modelo falló:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    _informar_importacion(informe, time.time() - inicio)

    proponente = ProponenteConModelo(
        para_rol(config, Rol.ENRIQUECIMIENTO), permitir_agregado=False
    )
    reparado, reparacion = reparar(curriculo, proponente, max_vueltas=vueltas)
    console.print(f"  {reparacion.resumen()}")

    pendientes = reparacion.pendientes_para_el_padre
    if pendientes:
        console.print()
        console.print("  [bold]Para que lo mires tú:[/bold]")
        for h in pendientes[:12]:
            color = "red" if h.severidad is Severidad.BLOQUEANTE else "yellow"
            donde = f" [dim]{h.objetivo}[/dim]" if h.objetivo else ""
            console.print(f"    [{color}]•[/{color}]{donde} {h.mensaje}")
        if len(pendientes) > 12:
            console.print(f"    [dim]… y {len(pendientes) - 12} más[/dim]")

    destino = salida or Path(f"{reparado.id}.yaml")
    guardar(reparado, destino)
    console.print()
    console.print(
        f"  [green]escrito[/green] [dim]{destino}[/dim]  "
        f"[dim]{time.time() - inicio:.0f}s en total[/dim]"
    )
    console.print()
    raise typer.Exit(code=0 if reparacion.ok else 1)


def main() -> None:  # pragma: no cover - punto de entrada
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
