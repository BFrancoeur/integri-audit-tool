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
    if [ "$#" -gt 0 ] && [ "$1" != "--help" ] && [ "$1" != "-h" ]; then
        echo "Unknown option: $1. Try 'ia --help'." >&2
        return 1
    fi

    echo "Integri Audit Tool — per-category aliases (each forwards extra args to 'integri-audit run')"
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

unset _integri_audit_tool_root
