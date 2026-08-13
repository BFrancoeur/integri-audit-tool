"""Human-in-the-loop attestation prompts, shared by any interactive Check.

A single, generic yes/no (+ optional named-authorizer) prompt, reused by
every check that sets `Check.interactive=True` — not built one-off for any
single category. Kept as its own module, out of runner.py, for the same
reason cli_progress_reporter.py is kept out of core: this is presentation
(blocking terminal I/O), not interpretation logic, and runner.py should stay
testable without a real terminal.

Must never be called while a database transaction is open — db.py enforces
a 60-second idle-in-transaction timeout, and a human's response time can
easily exceed that. runner.py only calls this after a check's savepoint has
already closed (see run_audit's per-check loop).
"""

from __future__ import annotations

from rich.console import Console

_YES_ANSWERS = ("y", "yes")


def prompt_attestation(
    question: str,
    *,
    require_authorizer_name: bool,
    console: Console | None = None,
) -> tuple[bool, str | None]:
    """Prints `question`, asks for yes/no, and — when require_authorizer_name
    is True and the answer is yes — a name to record as the accountable
    person. Returns (confirmed, authorizer_name).

    On EOFError (no interactive stdin, e.g. a piped/non-interactive
    invocation) returns (False, None) without hanging or crashing — the same
    fallback cli_progress_reporter.py's _wait_for_enter already uses for the
    --step gate.
    """
    console = console or Console(stderr=True)
    console.print(f"[bold]{question}[/bold]")
    try:
        answer = input("Confirm? [y/N]: ").strip().lower()
    except EOFError:
        return False, None

    confirmed = answer in _YES_ANSWERS
    if not confirmed:
        return False, None

    authorizer_name: str | None = None
    if require_authorizer_name:
        try:
            authorizer_name = input("Who authorized/owns this? ").strip() or None
        except EOFError:
            authorizer_name = None
    return True, authorizer_name
