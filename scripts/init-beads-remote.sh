#!/usr/bin/env bash
# Manually pre-initialize the beads Dolt remote for a tracked project.
#
# The merger agent does this automatically on first run, so you only need
# this script if you want to set the remote up before any merge happens.
#
# Usage:   bash scripts/init-beads-remote.sh <path-to-tracked-project>
# Example: bash scripts/init-beads-remote.sh ~/Projects/my-app
#
# Creates <project>/.beads-remote/ as a local Dolt repo.
# Idempotent: safe to run multiple times.

set -euo pipefail

if [ $# -eq 0 ]; then
    echo "Usage: $0 <path-to-tracked-project>" >&2
    echo "Example: $0 ~/Projects/my-app" >&2
    exit 1
fi

PROJECT_PATH="$(cd "$1" && pwd)"
REMOTE_DIR="${PROJECT_PATH}/.beads-remote"
BEADS_REMOTE="file://${REMOTE_DIR}"

info() { echo "[init-beads-remote] $*"; }

# ── Ensure dolt user identity is configured ──────────────────────────────────
ensure_dolt_identity() {
    local current_email
    current_email=$(dolt config --global --get user.email 2>/dev/null || true)
    if [ -n "$current_email" ]; then
        return
    fi
    # Fall back to git global config values if available
    local author_email author_name
    author_email=$(git config --global user.email 2>/dev/null || echo "dev@beads.local")
    author_name=$(git config --global user.name 2>/dev/null || echo "Dev")
    dolt config --global --add user.email "$author_email"
    dolt config --global --add user.name "$author_name"
    info "Configured dolt identity: $author_name <$author_email>"
}

# ── Create and init the Dolt remote repo ─────────────────────────────────────
init_remote() {
    if [ -d "${REMOTE_DIR}/.dolt" ]; then
        info "Remote already initialized at ${REMOTE_DIR} (idempotent)"
        return
    fi
    mkdir -p "$REMOTE_DIR"
    ( cd "$REMOTE_DIR" && dolt init )
    info "Initialized Dolt remote at ${REMOTE_DIR}"
}

ensure_dolt_identity
init_remote

info "Done. Beads remote for ${PROJECT_PATH}:"
info "  ${BEADS_REMOTE}"
