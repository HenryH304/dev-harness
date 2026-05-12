#!/usr/bin/env bash
# Initialize the shared local Dolt remote for beads.
# All worktrees in this project point here to share beads state.
#
# Usage:   bash scripts/init-beads-remote.sh
# Env var: BEADS_REMOTE_PATH   file:// URL of the remote (default: file://<project-root>/.beads-remote)
#
# Idempotent: safe to run multiple times.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Allow callers to pass a file:// URL; default to <project-root>/.beads-remote
BEADS_REMOTE_PATH="${BEADS_REMOTE_PATH:-file://${PROJECT_ROOT}/.beads-remote}"

info() { echo "[init-beads-remote] $*"; }

# Strip file:// prefix to get the bare filesystem path
if [[ "$BEADS_REMOTE_PATH" == file://* ]]; then
    REMOTE_DIR="${BEADS_REMOTE_PATH#file://}"
else
    # Bare path passed — treat as-is (not a valid bd remote URL, but accept for compat)
    REMOTE_DIR="$BEADS_REMOTE_PATH"
    BEADS_REMOTE_PATH="file://${REMOTE_DIR}"
fi

# ── Ensure dolt user identity is configured ──────────────────────────────────
ensure_dolt_identity() {
    local current_email
    current_email=$(dolt config --global --get user.email 2>/dev/null || true)
    if [ -n "$current_email" ]; then
        return
    fi
    # Try to read from the project .env
    local env_file="$PROJECT_ROOT/.env"
    local author_email="dev@beads.local"
    local author_name="Dev"
    if [ -f "$env_file" ]; then
        local val
        val=$(grep "^GIT_AUTHOR_EMAIL=" "$env_file" | cut -d= -f2- || true)
        [ -n "$val" ] && author_email="$val"
        val=$(grep "^GIT_AUTHOR_NAME=" "$env_file" | cut -d= -f2- || true)
        [ -n "$val" ] && author_name="$val"
    fi
    dolt config --global --add user.email "$author_email"
    dolt config --global --add user.name "$author_name"
    info "Configured dolt identity: $author_name <$author_email>"
}

# ── Create and init the Dolt remote repo ─────────────────────────────────────
init_remote() {
    if [ -d "$REMOTE_DIR/.dolt" ]; then
        info "Remote already initialized at $REMOTE_DIR (idempotent)"
        return
    fi
    mkdir -p "$REMOTE_DIR"
    ( cd "$REMOTE_DIR" && dolt init )
    info "Initialized Dolt remote at $REMOTE_DIR"
}

# ── Write BEADS_REMOTE_PATH to <project-root>/.env ───────────────────────────
update_env() {
    local env_file="$PROJECT_ROOT/.env"
    if [ -f "$env_file" ]; then
        if grep -q "^BEADS_REMOTE_PATH=" "$env_file"; then
            info "BEADS_REMOTE_PATH already in .env"
        else
            echo "BEADS_REMOTE_PATH=${BEADS_REMOTE_PATH}" >> "$env_file"
            info "Added BEADS_REMOTE_PATH to .env"
        fi
    else
        echo "BEADS_REMOTE_PATH=${BEADS_REMOTE_PATH}" > "$env_file"
        info "Created .env with BEADS_REMOTE_PATH"
    fi
}

ensure_dolt_identity
init_remote
update_env

info "Done. BEADS_REMOTE_PATH=${BEADS_REMOTE_PATH}"
