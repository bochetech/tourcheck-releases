"""CLI de Aula.

Por ahora expone el validador, que es la pieza de la que depende todo lo demás:
es el bucle de retroalimentación con el que el importador se corrige solo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from aula.curriculum.io import cargar
from aula.curriculum.validator import Severidad, validar

app = typer.Typer(help="Aula — tutoría con IA anclada a un currículo validado.")
curriculum_app = typer.Typer(help="Importar, validar y versionar planes de estudio.")
app.add_typer(curriculum_app, name="curriculum")

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


def main() -> None:  # pragma: no cover - punto de entrada
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
