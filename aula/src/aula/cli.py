"""CLI de Aula.

Por ahora expone el validador, que es la pieza de la que depende todo lo demás:
es el bucle de retroalimentación con el que el importador se corrige solo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from aula.config import ROLES_CARA_AL_NINO, Rol, cargar_config
from aula.curriculum.io import cargar
from aula.curriculum.validator import Severidad, validar

app = typer.Typer(help="Aula — tutoría con IA anclada a un currículo validado.")
curriculum_app = typer.Typer(help="Importar, validar y versionar planes de estudio.")
config_app = typer.Typer(help="Ver y comprobar la configuración de modelos.")
app.add_typer(curriculum_app, name="curriculum")
app.add_typer(config_app, name="config")

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


def main() -> None:  # pragma: no cover - punto de entrada
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
