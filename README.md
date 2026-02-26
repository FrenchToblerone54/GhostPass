# GhostPass

**GhostPass** is an MIT-licensed Python Telegram bot that serves as a consumer-facing VPN sales storefront for a [GhostGate](https://github.com/FrenchToblerone54/ghostgate) instance.

**Architecture:** User → GhostPass Bot → GhostGate REST API → 3x-ui nodes

---

## Quick Start

```bash
wget https://raw.githubusercontent.com/FrenchToblerone54/ghostpass/main/scripts/install.sh -O install.sh
chmod +x install.sh
sudo ./install.sh
```

The script will ask for:
1. **Bot Token** — from [@BotFather](https://t.me/BotFather)
2. **Admin Telegram User ID** — your numeric Telegram ID
3. **Language** — `en` (English) or `fa` (Persian/فارسی)
4. **Bot proxy URL** — optional, leave empty if not needed
5. **Auto-update** — automatically update the bot binary when new releases are available

Everything else is configured through the bot's first-run setup wizard.

---

## First-Run Setup Wizard

After installation, open Telegram and send `/start` to your bot as the admin. The wizard will guide you through:

1. **GhostGate URL** — the full panel URL including the secret path (e.g. `https://vpn.example.com/mySecretPath`). The bot tests the connection before saving.
2. **Support contact** — a @username users can contact for support.
3. **Card-to-Card payment** — card number and cardholder name (primary payment method for Iranian users).
4. **Cryptomus** — merchant ID and API key (optional, for crypto payments).
5. **Currencies** — configure one or more currencies (e.g. `IRT`, `USD`, `USDT`) with exchange rates and which payment methods accept each currency.

---

## Admin Panel

Admins access the full management interface by sending `/start`. The menu is entirely inline-keyboard driven and never appears in user autocomplete.

### Subscriptions
- Browse all subscriptions live from GhostGate (paginated, searchable)
- View stats and QR code for any subscription
- Manually create subscriptions with custom parameters and node selection
- Delete subscriptions

### Plans
- Create, edit, delete plans
- Select which GhostGate nodes/inbounds each plan uses
- Toggle active/inactive
- Edit price and name inline

### Users
- Search by Telegram ID or @username
- View user details and order history
- Ban / unban users

### Admins
- Add additional admins by Telegram ID with configurable permissions
- Remove admins (root admin cannot be removed)

### Orders
- View pending orders needing action
- View paid and rejected order history
- Manually confirm or reject pending card payments

### Settings
- **GhostGate Connection** — update URL with live connection test
- **Card-to-Card** — toggle, edit card number and cardholder name
- **Cryptomus** — toggle, edit merchant ID and API key
- **Request Flow** — toggle subscription request feature
- **Support Contact** — update support @username
- **Currencies** — add, edit, or remove currencies; set exchange rates and accepted payment methods per currency; set base currency
- **Sync Interval** — update background sync interval

---

## Payment Methods

### Card-to-Card (Primary)
Works with zero other configuration. Users:
1. Select a plan → see card details and price in their currency
2. Send a receipt screenshot
3. Admin receives the receipt with Confirm/Reject buttons
4. On confirmation, subscription is created automatically

### Cryptomus (Optional)
Configure via Settings → Cryptomus. Only shown if configured.

Webhook URL for faster payment confirmation:
```
http://YOUR_SERVER:8090/webhook/cryptomus
```

Sign up at [cryptomus.com](https://cryptomus.com).

### Request Flow (Optional)
Toggle via Settings → Request Flow. Users submit a request with optional reason; admin approves or declines.

---

## systemd Commands

```bash
sudo systemctl status ghostpass
sudo systemctl restart ghostpass
sudo journalctl -u ghostpass -f
```

---

## .env Reference

| Variable | Set by | Description |
|---|---|---|
| `BOT_TOKEN` | install.sh | Telegram bot token from @BotFather |
| `ADMIN_ID` | install.sh | Root admin Telegram user ID |
| `BOT_PROXY` | install.sh | Optional proxy URL for Telegram API |
| `LANGUAGE` | install.sh | `en` or `fa` |
| `GHOSTGATE_URL` | first-run wizard | Full GhostGate panel URL with secret path |
| `SYNC_INTERVAL` | install.sh | Background sync interval in seconds |
| `AUTO_UPDATE` | install.sh | `true` or `false` — auto-update binary on new releases |
| `UPDATE_CHECK_INTERVAL` | install.sh | How often to check for updates in seconds |
| `DB_PATH` | install.sh | SQLite database path |
| `LOG_FILE` | install.sh | Log file path |

Payment credentials (card number, Cryptomus keys) and currency configuration are stored in the SQLite `settings` table and never go in `.env`.

---

## Community

Join the Telegram channel for updates and announcements: [@GhostSoftDev](https://t.me/GhostSoftDev)

---

## License

MIT License - See LICENSE file for details
