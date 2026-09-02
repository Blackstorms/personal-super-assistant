# Shared helper: make sure `node` + `npm` exist.
# Sourced by build-desktop.sh / install.sh (not executed directly).

psa_prepend_path() {
  local d="$1"
  [[ -d "$d" ]] || return 0
  case ":$PATH:" in
    *":$d:"*) ;;
    *) PATH="$d:$PATH" ;;
  esac
}

psa_refresh_node_path() {
  psa_prepend_path "/opt/homebrew/bin"
  psa_prepend_path "/usr/local/bin"
  psa_prepend_path "$HOME/.local/bin"
  psa_prepend_path "$HOME/.nvm/current/bin"
  if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
    # shellcheck disable=SC1091
    . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1 || true
  fi
  local nvm_versions="$HOME/.nvm/versions/node"
  if [[ -d "$nvm_versions" ]]; then
    local latest
    latest="$(ls -1 "$nvm_versions" 2>/dev/null | sort | tail -1 || true)"
    if [[ -n "$latest" ]]; then
      psa_prepend_path "$nvm_versions/$latest/bin"
    fi
  fi
  export PATH
}

psa_ensure_npm() {
  psa_refresh_node_path
  if command -v npm >/dev/null 2>&1 && command -v node >/dev/null 2>&1; then
    echo "[PSA] node $(node -v)  npm $(npm -v)"
    return 0
  fi

  echo "[PSA] npm/node not on PATH; installing Node.js LTS..."
  if command -v brew >/dev/null 2>&1; then
    brew install node
    psa_refresh_node_path
  else
    echo "[PSA] ERROR: npm not found, and Homebrew is not installed."
    echo "[PSA] Install Node.js LTS from https://nodejs.org/  or: brew install node"
    echo "[PSA] Then open a new terminal and retry."
    return 1
  fi

  if ! command -v npm >/dev/null 2>&1 || ! command -v node >/dev/null 2>&1; then
    echo "[PSA] ERROR: npm still missing after install. Open a new terminal and retry."
    return 1
  fi
  echo "[PSA] node $(node -v)  npm $(npm -v)"
}
