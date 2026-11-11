"""CLI агента. Команды, которые реализуются в следующих задачах, честно сообщают об этом."""

from __future__ import annotations

from enum import StrEnum

import typer

from lnrbank.config import load_settings
from lnrbank.net.tls import CABundleMissing, check_tls

app = typer.Typer(help="Агент сравнения розничных продуктов банков в ЛНР", no_args_is_help=True)


class Mode(StrEnum):
    block = "block"
    full = "full"
    update = "update"


def _not_ready(task: int) -> None:
    typer.echo(f"Команда пока не реализована (задача {task}).", err=True)
    raise typer.Exit(code=2)


@app.command()
def check(tls_only: bool = typer.Option(False, "--tls-only", help="Только проверка TLS")) -> None:
    """Этапы 0–1: TLS, доступ, привязка к ЛНР, присутствие банков."""
    settings = load_settings()
    try:
        results = check_tls(settings)
    except CABundleMissing as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    for r in results:
        typer.echo(f"{'OK  ' if r.ok else 'FAIL'} {r.host:<28} {r.detail}")
    if not all(r.ok for r in results):
        raise typer.Exit(code=1)
    if not tls_only:
        from lnrbank.check import format_report, run_check

        typer.echo(format_report(run_check(settings)))


@app.command()
def run(
    mode: Mode = typer.Option(..., "--mode"),
    block: str | None = typer.Option(None, "--block"),
    collect_only: bool = typer.Option(False, "--collect-only"),
) -> None:
    """Сбор и анализ: block | full | update."""
    _not_ready(8)


@app.command()
def build() -> None:
    """Пересборка Excel и HTML из базы."""
    _not_ready(9)


@app.command()
def notify(test: bool = typer.Option(False, "--test")) -> None:
    """Отправка сводки в Telegram."""
    _not_ready(9)


if __name__ == "__main__":
    app()
