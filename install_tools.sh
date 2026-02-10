#!/bin/bash
# ============================================================
# Script di installazione tool per Bug Bounty Scanner PRO
# Supporta: Linux (Debian/Ubuntu, Arch, Fedora) e macOS
# ============================================================

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
fail() { echo -e "  ${RED}[!!]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[--]${NC} $1"; }
info() { echo -e "  $1"; }

echo ""
echo "  ============================================"
echo "  Bug Bounty Scanner PRO - Installer"
echo "  ============================================"
echo ""

# Rileva OS
OS="unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
    if command -v apt-get &>/dev/null; then
        PKG="apt"
    elif command -v pacman &>/dev/null; then
        PKG="pacman"
    elif command -v dnf &>/dev/null; then
        PKG="dnf"
    fi
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
    PKG="brew"
fi

info "Sistema: $OS ($PKG)"
echo ""

# Verifica Go (necessario per i tool ProjectDiscovery)
install_go_tools() {
    if ! command -v go &>/dev/null; then
        warn "Go non installato. Installo..."
        if [[ "$PKG" == "apt" ]]; then
            sudo apt-get update -qq && sudo apt-get install -y -qq golang-go
        elif [[ "$PKG" == "brew" ]]; then
            brew install go
        elif [[ "$PKG" == "pacman" ]]; then
            sudo pacman -S --noconfirm go
        elif [[ "$PKG" == "dnf" ]]; then
            sudo dnf install -y golang
        fi
    fi
    ok "Go $(go version 2>/dev/null | awk '{print $3}')"
}

# --- SUBFINDER ---
install_subfinder() {
    info "Installazione Subfinder..."
    if command -v subfinder &>/dev/null; then
        ok "Subfinder già installato"
        return
    fi
    go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest 2>/dev/null
    ok "Subfinder installato"
}

# --- HTTPX ---
install_httpx() {
    info "Installazione httpx..."
    if command -v httpx &>/dev/null; then
        ok "httpx già installato"
        return
    fi
    go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest 2>/dev/null
    ok "httpx installato"
}

# --- NUCLEI ---
install_nuclei() {
    info "Installazione Nuclei..."
    if command -v nuclei &>/dev/null; then
        ok "Nuclei già installato"
        return
    fi
    go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest 2>/dev/null
    ok "Nuclei installato"
    info "  Aggiornamento template Nuclei..."
    nuclei -update-templates 2>/dev/null || true
}

# --- FFUF ---
install_ffuf() {
    info "Installazione ffuf..."
    if command -v ffuf &>/dev/null; then
        ok "ffuf già installato"
        return
    fi
    go install github.com/ffuf/ffuf/v2@latest 2>/dev/null
    ok "ffuf installato"
}

# --- DALFOX ---
install_dalfox() {
    info "Installazione Dalfox..."
    if command -v dalfox &>/dev/null; then
        ok "Dalfox già installato"
        return
    fi
    go install github.com/hahwul/dalfox/v2@latest 2>/dev/null
    ok "Dalfox installato"
}

# --- NMAP ---
install_nmap() {
    info "Installazione Nmap..."
    if command -v nmap &>/dev/null; then
        ok "Nmap già installato"
        return
    fi
    if [[ "$PKG" == "apt" ]]; then
        sudo apt-get install -y -qq nmap
    elif [[ "$PKG" == "brew" ]]; then
        brew install nmap
    elif [[ "$PKG" == "pacman" ]]; then
        sudo pacman -S --noconfirm nmap
    elif [[ "$PKG" == "dnf" ]]; then
        sudo dnf install -y nmap
    fi
    ok "Nmap installato"
}

# --- SQLMAP ---
install_sqlmap() {
    info "Installazione SQLMap..."
    if command -v sqlmap &>/dev/null; then
        ok "SQLMap già installato"
        return
    fi
    pip install sqlmap --quiet 2>/dev/null || pip3 install sqlmap --quiet 2>/dev/null
    ok "SQLMap installato"
}

# --- NIKTO ---
install_nikto() {
    info "Installazione Nikto..."
    if command -v nikto &>/dev/null; then
        ok "Nikto già installato"
        return
    fi
    if [[ "$PKG" == "apt" ]]; then
        sudo apt-get install -y -qq nikto
    elif [[ "$PKG" == "brew" ]]; then
        brew install nikto
    elif [[ "$PKG" == "pacman" ]]; then
        sudo pacman -S --noconfirm nikto
    elif [[ "$PKG" == "dnf" ]]; then
        sudo dnf install -y nikto
    fi
    ok "Nikto installato"
}

# --- DIPENDENZE PYTHON ---
install_python_deps() {
    info "Installazione dipendenze Python..."
    pip install -r requirements.txt --quiet 2>/dev/null || pip3 install -r requirements.txt --quiet 2>/dev/null
    ok "Dipendenze Python installate"
}

# ============ ESECUZIONE ============

echo "  --- Dipendenze Python ---"
install_python_deps
echo ""

echo "  --- Go e tool Go ---"
install_go_tools
install_subfinder
install_httpx
install_nuclei
install_ffuf
install_dalfox
echo ""

echo "  --- Tool di sistema ---"
install_nmap
install_sqlmap
install_nikto
echo ""

# Aggiungi GOPATH al PATH se necessario
GOPATH="${GOPATH:-$HOME/go}"
if [[ ":$PATH:" != *":$GOPATH/bin:"* ]]; then
    warn "Aggiungi al tuo .bashrc o .zshrc:"
    info "  export PATH=\$PATH:$GOPATH/bin"
fi

echo ""
echo "  ============================================"
echo "  Installazione completata!"
echo "  ============================================"
echo ""
echo "  Verifica con:"
echo "    python -m bugbounty_scanner.cli_pro -t example.com --check"
echo ""
echo "  Scansione completa:"
echo "    python -m bugbounty_scanner.cli_pro -t TARGET"
echo ""
