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
