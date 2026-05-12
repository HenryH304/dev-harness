#!/usr/bin/env bash
# Install host-side dependencies: dolt and beads (bd)
# Run once per machine; safe to re-run (idempotent).
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

info()    { echo -e "${BOLD}[install-deps]${RESET} $*"; }
success() { echo -e "${GREEN}[install-deps]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[install-deps]${RESET} $*"; }

# ── dolt ──────────────────────────────────────────────────────────────────────
install_dolt() {
    if command -v dolt &>/dev/null; then
        success "dolt already installed: $(dolt version)"
        return
    fi
    info "Installing dolt..."
    curl -L https://github.com/dolthub/dolt/releases/latest/download/install.sh | bash
    success "dolt installed: $(dolt version)"
}

# ── beads (bd) ────────────────────────────────────────────────────────────────
install_beads() {
    if command -v bd &>/dev/null; then
        success "bd already installed: $(bd version 2>&1 || true)"
        return
    fi
    info "Installing beads (bd) via Go..."
    if ! command -v go &>/dev/null; then
        warn "Go not found. Trying curl install script instead..."
        curl -fsSL https://raw.githubusercontent.com/gastownhall/beads/main/scripts/install.sh | bash
        return
    fi
    # CGO_ENABLED=0 for a server-mode build — no C compiler required
    CGO_ENABLED=0 go install github.com/steveyegge/beads/cmd/bd@latest
    # Ensure bd is on PATH (go/bin may not be in PATH)
    if [ -f "$HOME/go/bin/bd" ] && ! command -v bd &>/dev/null; then
        mkdir -p "$HOME/.local/bin"
        ln -sf "$HOME/go/bin/bd" "$HOME/.local/bin/bd"
    fi
    success "bd installed: $(bd version 2>&1 || true)"
}

install_dolt
install_beads

info "Verifying installations..."
dolt version
bd version

success "All dependencies installed successfully."
