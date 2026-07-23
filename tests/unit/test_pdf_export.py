import subprocess
from pathlib import Path

import pytest
from rich.console import Console

from integri_audit_tool import pdf_export


def test_is_pandoc_available_reflects_shutil_which(mocker):
    mocker.patch.object(pdf_export.shutil, "which", return_value="/usr/bin/pandoc")
    assert pdf_export.is_pandoc_available() is True

    mocker.patch.object(pdf_export.shutil, "which", return_value=None)
    assert pdf_export.is_pandoc_available() is False


def test_convert_markdown_to_pdf_raises_when_pandoc_missing(mocker):
    mocker.patch.object(pdf_export, "is_pandoc_available", return_value=False)

    with pytest.raises(pdf_export.PdfConversionError, match="not installed"):
        pdf_export.convert_markdown_to_pdf(
            Path("report.md"), Path("report.pdf"), Console(stderr=True), show_progress=False
        )


def test_convert_markdown_to_pdf_raises_with_stderr_when_subprocess_fails(mocker):
    mocker.patch.object(pdf_export, "is_pandoc_available", return_value=True)
    mocker.patch.object(
        pdf_export.subprocess,
        "run",
        side_effect=subprocess.CalledProcessError(
            returncode=1, cmd=["pandoc"], stderr="! LaTeX Error: pdflatex not found"
        ),
    )

    with pytest.raises(pdf_export.PdfConversionError, match="pdflatex not found"):
        pdf_export.convert_markdown_to_pdf(
            Path("report.md"), Path("report.pdf"), Console(stderr=True), show_progress=False
        )


def test_convert_markdown_to_pdf_succeeds_when_subprocess_succeeds(mocker):
    mocker.patch.object(pdf_export, "is_pandoc_available", return_value=True)
    mock_run = mocker.patch.object(pdf_export.subprocess, "run")

    pdf_export.convert_markdown_to_pdf(
        Path("report.md"), Path("report.pdf"), Console(stderr=True), show_progress=False
    )

    mock_run.assert_called_once()


def test_convert_markdown_to_pdf_uses_xelatex_and_styling_files(mocker):
    """pdflatex can't use pdf_style.tex's fontspec-based system fonts (Open Sans /
    Lora) — the engine must be xelatex, with the style/lua-filter files attached,
    since both ship alongside pdf_export.py and are expected to exist."""
    mocker.patch.object(pdf_export, "is_pandoc_available", return_value=True)
    mock_run = mocker.patch.object(pdf_export.subprocess, "run")

    pdf_export.convert_markdown_to_pdf(
        Path("report.md"), Path("report.pdf"), Console(stderr=True), show_progress=False
    )

    command = mock_run.call_args[0][0]
    assert command[:4] == ["pandoc", "report.md", "-o", "report.pdf"]
    assert "--pdf-engine=xelatex" in command
    assert any(arg.startswith("--include-in-header=") and arg.endswith("pdf_style.tex") for arg in command)
    assert any(
        arg.startswith("--lua-filter=") and arg.endswith("pandoc_table_header_font.lua") for arg in command
    )
