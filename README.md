# BillMonitor

An [AppDaemon](https://appdaemon.readthedocs.io/) app for Home Assistant that monitors a Gmail "Bills" label, extracts bill amounts and due dates, and sends them to Home Assistant via webhook. HA then creates a to-do item and sends a notification to your phones.

## How It Works

1. Every 15 minutes, BillMonitor scans Gmail for unread emails in the "Bills" label
2. Each email is matched against `bill_config.yaml` by sender domain
3. Amount and due date are extracted via regex
4. A webhook payload is sent to Home Assistant with `bill_name`, `amount`, `due_date`, and `split`
5. The email is marked as read so it isn't processed again
6. A SQLite database tracks processed bills to prevent duplicate notifications

---

## Prerequisites

- Home Assistant (HA OS or Supervised)
- [AppDaemon add-on](https://github.com/hassio-addons/addon-appdaemon) (v4.x)
- A Google Cloud project with the Gmail API enabled
- Gmail with a "Bills" label applied to billing emails

---

## Setup

### 1. Enable the Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use an existing one)
3. Enable the **Gmail API** for the project
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
5. Choose **Desktop app**, download the JSON, and rename it `credentials.json`

### 2. Install the AppDaemon Add-on

In Home Assistant:
1. Go to **Settings → Add-ons → Add-on Store**
2. Search for **AppDaemon** and install it
3. In the add-on configuration, add the following under `python_packages`:
   ```
   google-api-python-client
   google-auth-oauthlib
   google-auth-httplib2
   beautifulsoup4
   requests
   pyyaml
   ```
4. Start the add-on

### 3. Copy Files to Home Assistant

Copy the `billmonitor/` package folder into AppDaemon's apps directory:

```
/addon_configs/a0d7b954_appdaemon/apps/billmonitor/
```

Copy `bill_config.yaml` to the HA config root (not inside the apps folder):

```
/config/bill_config.yaml
```

Place `credentials.json` inside the billmonitor folder:

```
/addon_configs/a0d7b954_appdaemon/apps/billmonitor/credentials.json
```

### 4. Authenticate with Gmail

Run `setup_auth.py` **locally on your desktop** (not on the Pi) — it opens a browser for OAuth consent:

```bash
pip install google-auth-oauthlib
python billmonitor/setup_auth.py
```

This creates `token.json`. Copy it to the Pi:

```
/addon_configs/a0d7b954_appdaemon/apps/billmonitor/token.json
```

> If you ever need to re-authenticate (e.g. scope changes), delete `token.json` and re-run `setup_auth.py`.

### 5. Create the AppDaemon Secrets File

Create `/addon_configs/a0d7b954_appdaemon/secrets.yaml` with your webhook URL:

```yaml
bill_webhook_url: http://homeassistant.local:8123/api/webhook/YOUR_WEBHOOK_ID
```

### 6. Configure apps.yaml

Add the following to `/addon_configs/a0d7b954_appdaemon/apps/apps.yaml`:

```yaml
bill_monitor:
    module: billmonitor.billmonitor
    class: BillMonitor
    credentials_path: "billmonitor/credentials.json"
    token_path: "billmonitor/token.json"
    db_path: "billmonitor/state.db"
    bill_config_path: "/config/bill_config.yaml"
    gmail_label: "Bills"
    check_interval_seconds: 900
    webhook_url: !secret bill_webhook_url
```

### 7. Set Up the HA Webhook Automation

In Home Assistant, create an automation triggered by the webhook that:
- Creates a to-do item with the bill name, amount, due date, and split
- Sends a notification to your devices

The webhook payload fields are: `bill_name`, `amount`, `due_date`, `split`

---

## Configuring Bills (`bill_config.yaml`)

Each entry matches a sender and defines how to extract the amount and due date:

```yaml
bills:
  - sender_match: "example.com"       # case-insensitive substring of the From header
    bill_name: "Example Bill"
    split_divisor: 2                   # amount / split_divisor = split field sent to HA
    amount:
      pattern: '\$([0-9]+(?:\.[0-9]{2})?)'   # regex with one capturing group
    due_date:
      pattern: 'Due Date:\s*(\d{2}/\d{2}/\d{4})'
      input_format: "%m/%d/%Y"         # strptime format (list accepted for multiple formats)
      output_format: "%m/%d/%y"        # strftime format sent to HA
```

> **Important:** `bill_config.yaml` must live at `/config/bill_config.yaml` (the HA config root), NOT inside the AppDaemon apps folder. AppDaemon scans all `.yaml` files in the apps directory as app configs — placing it there causes errors.

> **Tip:** After editing `bill_config.yaml`, bump the version comment in `apps.yaml` (e.g. `# v5` → `# v6`) to force AppDaemon to reinitialize the app and pick up the changes.

---

## File Structure

```
BillMonitor/
├── billmonitor/
│   ├── __init__.py
│   ├── billmonitor.py      # AppDaemon app — main loop and orchestration
│   ├── email_parser.py     # Regex extraction for amounts and dates
│   ├── gmail_client.py     # Gmail API wrapper (OAuth2)
│   ├── setup_auth.py       # Run locally to generate token.json
│   └── state_db.py         # SQLite wrapper for deduplication
├── bill_config.yaml        # Per-bill sender/regex configuration
├── requirements.txt        # Python dependencies
└── parseEmails.py          # Original v1 prototype (IMAP, superseded)
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `!secret used but no secrets file found` | Create `/addon_configs/a0d7b954_appdaemon/secrets.yaml` |
| `BadAppConfigFile: bill_config.yaml` | Move `bill_config.yaml` out of the apps folder to `/config/` |
| `No module named 'billmonitor'` | Ensure `__init__.py` exists in the `billmonitor/` folder |
| `No module named 'email_parser'` | Imports must be relative (`.email_parser`) — confirms `__init__.py` is present |
| `Date normalization failed` | Check `input_format` in `bill_config.yaml` matches the actual email text |
| `No bill config for sender: '...'` | Check `sender_match` for typos against the actual From address in the email |
| `invalid_scope: Bad Request` | Re-run `setup_auth.py` after any scope change to regenerate `token.json` |
| Config changes not picked up | Bump version comment in `apps.yaml` to force app reinit |
