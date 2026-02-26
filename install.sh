#!/bin/bash
set -e

REPO="https://github.com/FrenchToblerone54/ghostpass"
INSTALL_DIR="/opt/ghostpass"
SERVICE_FILE="/etc/systemd/system/ghostpass.service"
ENV_FILE="$INSTALL_DIR/.env"
LOG_FILE="/var/log/ghostpass.log"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║              GhostPass VPN Sales Bot                     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (use sudo)"
    exit 1
fi

ARCH=$(uname -m)
if [ "$ARCH" != "x86_64" ]; then
    echo "Error: Only x86_64 (amd64) architecture is supported"
    exit 1
fi

OS=$(uname -s)
if [ "$OS" != "Linux" ]; then
    echo "Error: Only Linux is supported"
    exit 1
fi

echo "Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Updating existing installation..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    echo "Cloning GhostPass..."
    git clone "$REPO" "$INSTALL_DIR" --depth=1
fi

echo "Setting up Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

touch "$LOG_FILE"

if [ ! -f "$ENV_FILE" ]; then
    echo ""
    echo "Configuration"
    echo "─────────────"
    echo ""

    read -p "Bot Token (from @BotFather): " BOT_TOKEN
    while [ -z "$BOT_TOKEN" ]; do
        echo "Bot token is required."
        read -p "Bot Token: " BOT_TOKEN
    done

    read -p "Admin Telegram User ID: " ADMIN_ID
    while [ -z "$ADMIN_ID" ]; do
        echo "Admin ID is required."
        read -p "Admin Telegram User ID: " ADMIN_ID
    done

    echo ""
    echo "Language / زبان"
    echo "  en = English"
    echo "  fa = Persian / فارسی"
    read -p "Language [en]: " LANGUAGE
    LANGUAGE=${LANGUAGE:-en}
    if [ "$LANGUAGE" != "fa" ] && [ "$LANGUAGE" != "en" ]; then
        LANGUAGE="en"
    fi

    echo ""
    read -p "Bot proxy URL (leave empty if not needed): " BOT_PROXY

    cat > "$ENV_FILE" <<EOF
BOT_TOKEN=${BOT_TOKEN}
ADMIN_ID=${ADMIN_ID}
BOT_PROXY=${BOT_PROXY}
LANGUAGE=${LANGUAGE}

GHOSTGATE_URL=
SYNC_INTERVAL=60

DB_PATH=${INSTALL_DIR}/ghostpass.db
LOG_FILE=${LOG_FILE}
EOF

    chmod 600 "$ENV_FILE"
    echo ""
    echo "Configuration saved."
else
    echo "Existing configuration found at $ENV_FILE — skipping prompt."
fi

echo ""
echo "Installing systemd service..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=GhostPass VPN Sales Bot
After=network.target

[Service]
Type=simple
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/main.py
EnvironmentFile=${ENV_FILE}
Restart=always
RestartSec=5
WorkingDirectory=${INSTALL_DIR}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ghostpass

if systemctl is-active --quiet ghostpass; then
    systemctl restart ghostpass
else
    systemctl start ghostpass
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║           GhostPass Installation Complete! ✅            ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                          ║"
echo "║  Next step: Open Telegram and send /start to your bot.  ║"
echo "║  The setup wizard will guide you through configuration.  ║"
echo "║                                                          ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Useful commands:                                        ║"
echo "║  sudo systemctl status ghostpass                         ║"
echo "║  sudo systemctl restart ghostpass                        ║"
echo "║  sudo journalctl -u ghostpass -f                         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
