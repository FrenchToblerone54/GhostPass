#!/bin/bash
set -e

GITHUB_REPO="FrenchToblerone54/ghostpass"
VERSION="latest"
INSTALL_DIR="/opt/ghostpass"
ENV_FILE="$INSTALL_DIR/.env"
LOG_FILE="/var/log/ghostpass.log"
SERVICE_FILE="/etc/systemd/system/ghostpass.service"
RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
BLUE="\033[0;34m"
CYAN="\033[0;36m"
MAGENTA="\033[0;35m"
BOLD="\033[1m"
DIM="\033[2m"
NC="\033[0m"

p_step() { echo -e "\n${BLUE}${BOLD}▶  $1${NC}"; }
p_ok() { echo -e "  ${GREEN}✓${NC}  $1"; }
p_warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; }
p_err() { echo -e "  ${RED}✗${NC}  $1" >&2; }
p_info() { echo -e "  ${CYAN}ℹ${NC}  $1"; }
p_ask() { echo -ne "  ${MAGENTA}?${NC}  $1"; }
p_sep() { echo -e "  ${DIM}------------------------------------------------------------${NC}"; }

clear
echo -e "${CYAN}${BOLD}"
echo "  ============================================================"
echo "    GhostPass VPN Sales Bot                                 "
echo "    Telegram Storefront for GhostGate                       "
echo "  ============================================================"
echo -e "${NC}"
echo -e "  ${DIM}Source: github.com/${GITHUB_REPO}${NC}"
echo ""

p_step "Checking prerequisites..."
if [ "$EUID" -ne 0 ]; then
    p_err "Please run as root (use sudo)"
    exit 1
fi
p_ok "Root access: OK"

ARCH=$(uname -m)
if [ "$ARCH" != "x86_64" ]; then
    p_err "Only x86_64 (amd64) architecture is supported"
    exit 1
fi
p_ok "CPU: x86_64 — OK"

OS=$(uname -s)
if [ "$OS" != "Linux" ]; then
    p_err "Only Linux is supported"
    exit 1
fi
p_ok "OS: Linux — OK"

p_step "Downloading GhostPass..."
apt-get install -y -qq wget
wget -q --show-progress "https://github.com/${GITHUB_REPO}/releases/${VERSION}/download/ghostpass" -O /tmp/ghostpass
wget -q "https://github.com/${GITHUB_REPO}/releases/${VERSION}/download/ghostpass.sha256" -O /tmp/ghostpass.sha256

p_step "Verifying checksum..."
cd /tmp
sha256sum -c ghostpass.sha256
p_ok "Checksum verified"

p_step "Installing binary..."
install -m 755 /tmp/ghostpass /usr/local/bin/ghostpass
p_ok "Binary installed to /usr/local/bin/ghostpass"

p_step "Creating directories..."
mkdir -p "$INSTALL_DIR"
touch "$LOG_FILE"
p_ok "Directories ready"

if [ ! -f "$ENV_FILE" ]; then
    p_step "Configuration"
    p_sep

    while true; do
        p_ask "Bot Token (from @BotFather): "; read -r BOT_TOKEN
        [ -n "$BOT_TOKEN" ] && break
        p_err "Bot token is required."
    done

    while true; do
        p_ask "Admin Telegram User ID: "; read -r ADMIN_ID
        [ -n "$ADMIN_ID" ] && break
        p_err "Admin ID is required."
    done

    p_sep
    p_info "Language / زبان"
    p_info "  en = English"
    p_info "  fa = Persian / فارسی"
    p_ask "Language [en]: "; read -r LANGUAGE
    LANGUAGE=${LANGUAGE:-en}
    [[ "$LANGUAGE" != "fa" && "$LANGUAGE" != "en" ]] && LANGUAGE="en"

    p_sep
    p_ask "Bot proxy URL (leave empty if not needed): "; read -r BOT_PROXY

    p_sep
    p_ask "Enable auto-update? [Y/n]: "; read -r AU
    AU=${AU:-y}
    if [[ $AU =~ ^[Yy]$ ]]; then
        AUTO_UPDATE="true"
    else
        AUTO_UPDATE="false"
    fi

    cat > "$ENV_FILE" <<EOF
BOT_TOKEN=${BOT_TOKEN}
ADMIN_ID=${ADMIN_ID}
BOT_PROXY=${BOT_PROXY}
LANGUAGE=${LANGUAGE}

GHOSTGATE_URL=
SYNC_INTERVAL=60

AUTO_UPDATE=${AUTO_UPDATE}
UPDATE_CHECK_INTERVAL=300

DB_PATH=${INSTALL_DIR}/ghostpass.db
LOG_FILE=${LOG_FILE}
EOF

    chmod 600 "$ENV_FILE"
    p_ok "Configuration saved to $ENV_FILE"
else
    p_warn "Existing configuration found at $ENV_FILE — skipping prompt."
fi

p_step "Installing systemd service..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=GhostPass VPN Sales Bot
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ghostpass
Restart=always
RestartSec=5
WorkingDirectory=${INSTALL_DIR}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
p_ok "Systemd service installed"

p_step "Enabling and starting GhostPass..."
systemctl enable ghostpass
if systemctl is-active --quiet ghostpass; then
    p_warn "Restarting existing service..."
    systemctl restart ghostpass
else
    systemctl start ghostpass
fi
p_ok "GhostPass is running"

p_sep
p_ok "Installation complete!"
p_sep
p_info "Next step: Open Telegram and send /start to your bot."
p_info "The setup wizard will guide you through configuration."
echo ""
p_info "Useful commands:"
echo -e "  ${DIM}sudo systemctl status ghostpass${NC}"
echo -e "  ${DIM}sudo systemctl restart ghostpass${NC}"
echo -e "  ${DIM}sudo journalctl -u ghostpass -f${NC}"
echo ""
