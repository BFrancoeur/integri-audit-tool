"""Converts the Markdown audit report to PDF via Pandoc.

Pandoc is a system binary, not a Python package — it can't live in
pyproject.toml's dependencies. It also has no built-in PDF renderer of its
own: producing a PDF additionally requires a PDF engine (a LaTeX
distribution, or wkhtmltopdf) installed separately. Both failure modes
(pandoc missing, or pandoc present but no engine) are treated the same way
by callers: catch PdfConversionError and continue with the Markdown report
alone, the same graceful-degradation pattern used throughout the audit
checks themselves (e.g. when pg_stat_statements isn't installed).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn


class PdfConversionError(RuntimeError):
    """Raised when Pandoc is missing or the conversion subprocess fails."""


_STYLE_TEX = Path(__file__).parent / "report" / "pdf_style.tex"
_TABLE_HEADER_FONT_LUA = Path(__file__).parent / "report" / "pandoc_table_header_font.lua"


def is_pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


def convert_markdown_to_pdf(
    markdown_path: Path, pdf_path: Path, console: Console, show_progress: bool = True
) -> None:
    """Runs `pandoc <markdown_path> -o <pdf_path>`.

    Raises PdfConversionError (with an actionable message) if pandoc isn't
    installed, or if the conversion subprocess fails — most commonly because
    no PDF engine (a LaTeX distribution, or wkhtmltopdf) is installed, in
    which case pandoc's own stderr explaining that is surfaced, not swallowed.
    """
    if not is_pandoc_available():
        raise PdfConversionError(
            "pandoc is not installed or not on PATH. Install it (e.g. `winget install --id=JohnMacFarlane.Pandoc`) "
            "to enable PDF generation."
        )

    progress = None
    if show_progress:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        )
        progress.start()
        progress.add_task("Creating PDF audit report...", total=None)

    # xelatex (not pdflatex, the default) is required for pdf_style.tex's
    # fontspec-based system fonts (Open Sans body / Lora Bold headings) —
    # pdflatex can only use LaTeX's built-in Computer Modern.
    command = ["pandoc", str(markdown_path), "-o", str(pdf_path), "--pdf-engine=xelatex"]
    if _STYLE_TEX.exists():
        command.append(f"--include-in-header={_STYLE_TEX}")
    if _TABLE_HEADER_FONT_LUA.exists():
        command.append(f"--lua-filter={_TABLE_HEADER_FONT_LUA}")

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise PdfConversionError(
            "pandoc failed to produce a PDF — this usually means no PDF engine "
            "(a LaTeX distribution like MiKTeX/TeX Live with xelatex, or wkhtmltopdf via "
            "`--pdf-engine=wkhtmltopdf`) is installed, or the fonts referenced in "
            "report/pdf_style.tex (Open Sans, Lora) aren't installed on this machine. "
            f"Pandoc's error:\n{exc.stderr.strip() if exc.stderr else '(no stderr captured)'}"
        ) from exc
    finally:
        if progress is not None:
            progress.stop()
