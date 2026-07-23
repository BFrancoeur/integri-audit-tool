#!/usr/bin/env bash
# Terse, category-relevant aliases for running one rubric category at a time.
# These must be SOURCED, not executed — `alias` only affects the current
# shell, so this has no effect run as a normal script.
#
# One-off use:
#   source scripts/aliases.sh
#
# Permanent use, add to ~/.bashrc (adjust the path):
#   source /path/to/integri-audit-tool/scripts/aliases.sh
#
# Each alias forwards extra args to `integri-audit run`, same as
# run-category.sh, e.g.: ia-schema --output report.md --no-pdf
#
# Run `ia --help` any time to list them all without leaving the CLI.

ia() {
    # ${BASH_SOURCE[0]} inside a function is the file the function was
    # *defined* in (this file), regardless of when/where it's later called —
    # unlike the module-scope $_integri_audit_tool_root below, which is
    # unset once sourcing finishes, so it can't be relied on here.
    local _root
    _root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

    if [ "$#" -gt 0 ] && [ "$1" = "run" ]; then
        shift
        "$_root/scripts/run-audit.sh" "$@"
        return $?
    fi

    if [ "$#" -gt 0 ] && [ "$1" != "--help" ] && [ "$1" != "-h" ]; then
        echo "Unknown option: $1. Try 'ia --help'." >&2
        return 1
    fi

    echo "Integri Audit Tool — per-category aliases (each forwards extra args to 'integri-audit run')"
    echo ""
    printf "  %-11s %s\n" "Command" "Description"
    printf "  %-11s %s\n" "-------" "-----------"
    printf "  %-11s %s\n" "ia run" "Full audit — prompts for client business name, names the report after it"
    echo ""
    printf "  %-11s %s\n" "Alias" "Category"
    printf "  %-11s %s\n" "-----" "--------"
    printf "  %-11s %s\n" "ia-schema"  "1. Schema Design & Normalization Boundaries"
    printf "  %-11s %s\n" "ia-jsonb"   "2. JSONB Structure & Governance"
    printf "  %-11s %s\n" "ia-index"   "3. Indexing Strategy"
    printf "  %-11s %s\n" "ia-fts"     "4. Full-Text & Structured Search Behavior"
    printf "  %-11s %s\n" "ia-query"   "5. Query Patterns & Application Interaction"
    printf "  %-11s %s\n" "ia-quality" "6. Data Quality & Integrity"
    printf "  %-11s %s\n" "ia-scale"   "7. Scale & Growth Readiness"
    printf "  %-11s %s\n" "ia-sec"     "8. Security & Access Boundaries"
    printf "  %-11s %s\n" "ia-backup"  "9. Backup, Recovery & Change Management"
    printf "  %-11s %s\n" "ia-mon"     "10. Monitoring & Observability"
    printf "  %-11s %s\n" "ia-docs"    "11. Documentation & Institutional Knowledge"
    echo ""
    printf "  %-11s %s\n" "ia-db-up"   "Set up/reuse the synthetic test database, auto-exports INTEGRI_DSN"
    printf "  %-11s %s\n" "ia-db-down" "Tear down the synthetic test database"
}

_integri_audit_tool_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

alias ia-schema="$_integri_audit_tool_root/scripts/run-category.sh 1"    # Schema Design & Normalization Boundaries
alias ia-jsonb="$_integri_audit_tool_root/scripts/run-category.sh 2"     # JSONB Structure & Governance
alias ia-index="$_integri_audit_tool_root/scripts/run-category.sh 3"    # Indexing Strategy
alias ia-fts="$_integri_audit_tool_root/scripts/run-category.sh 4"      # Full-Text & Structured Search Behavior
alias ia-query="$_integri_audit_tool_root/scripts/run-category.sh 5"    # Query Patterns & Application Interaction
alias ia-quality="$_integri_audit_tool_root/scripts/run-category.sh 6"  # Data Quality & Integrity
alias ia-scale="$_integri_audit_tool_root/scripts/run-category.sh 7"    # Scale & Growth Readiness
alias ia-sec="$_integri_audit_tool_root/scripts/run-category.sh 8"      # Security & Access Boundaries
alias ia-backup="$_integri_audit_tool_root/scripts/run-category.sh 9"   # Backup, Recovery & Change Management
alias ia-mon="$_integri_audit_tool_root/scripts/run-category.sh 10"     # Monitoring & Observability
alias ia-docs="$_integri_audit_tool_root/scripts/run-category.sh 11"    # Documentation & Institutional Knowledge

# Functions, not plain aliases: a script run as a subprocess can't export a
# variable into the shell that called it, so setup-synthetic-db.sh prints
# *only* the bare DSN to stdout (everything else goes to stderr) and this
# function captures + exports it directly — no more copy-pasting the
# printed `export INTEGRI_DSN=...` line by hand.
ia-db-up() {
    local _root dsn
    _root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    dsn="$("$_root/scripts/setup-synthetic-db.sh" "$@")" || return $?
    export INTEGRI_DSN="$dsn"
    echo "INTEGRI_DSN set for this shell session: $INTEGRI_DSN"
}

ia-db-down() {
    local _root
    _root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    "$_root/scripts/teardown-synthetic-db.sh" "$@" || return $?
    # Only clear it if it still points at the synthetic db this just tore
    # down — never clobber a DSN you set yourself for something else.
    if [ "${INTEGRI_DSN:-}" = "postgresql://postgres:synthetic@localhost:55432/synthetic_client" ]; then
        unset INTEGRI_DSN
        echo "INTEGRI_DSN unset."
    fi
}

unset _integri_audit_tool_root
