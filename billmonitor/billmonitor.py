"""
BillMonitor — AppDaemon app for Home Assistant OS.

Runs on a configurable schedule, fetches unread bill emails from Gmail via
the Gmail API, parses amount and due date, and fires a webhook to Home Assistant.

apps.yaml entry:
    bill_monitor:
      module: billmonitor.billmonitor
      class: BillMonitor
      credentials_path: "billmonitor/credentials.json"
      token_path: "billmonitor/token.json"
      db_path: "billmonitor/state.db"
      bill_config_path: "billmonitor/bill_config.yaml"
      gmail_label: "Bills"
      check_interval_seconds: 900
      webhook_url: !secret bill_webhook_url
"""

import os

import requests
import yaml
import appdaemon.plugins.hass.hassapi as hass

from .email_parser import extract_amount, extract_due_date, normalize_date
from .gmail_client import AuthError, GmailClient
from .state_db import StateDB


class BillMonitor(hass.Hass):
    def initialize(self):
        # Resolve paths relative to the AppDaemon apps directory
        apps_dir = os.path.dirname(os.path.abspath(__file__))

        credentials_path = self._resolve(apps_dir, self.args["credentials_path"])
        token_path = self._resolve(apps_dir, self.args["token_path"])
        db_path = self._resolve(apps_dir, self.args["db_path"])
        bill_config_path = self._resolve(apps_dir, self.args["bill_config_path"])

        self._gmail_label = self.args.get("gmail_label", "Bills")
        self._webhook_url = self.args["webhook_url"]
        interval = int(self.args.get("check_interval_seconds", 900))

        # Load bill configuration
        with open(bill_config_path, "r") as f:
            config = yaml.safe_load(f)
        self._bill_configs = config.get("bills", [])

        # Initialize dependencies
        self._gmail = GmailClient(credentials_path, token_path)
        self._db = StateDB(db_path)
        self._db.initialize()

        # Authenticate with Gmail (raises AuthError on failure — will show in logs)
        try:
            self._gmail.authenticate()
        except AuthError as e:
            self.log(str(e), level="ERROR")
            return

        self.log(
            f"BillMonitor initialized. Checking every {interval}s for unread emails "
            f"in Gmail label '{self._gmail_label}'.",
            level="INFO",
        )

        # Schedule: run now and then every `interval` seconds
        self.run_every(self.run_check, "now", interval)

    # ------------------------------------------------------------------
    # Scheduler callback
    # ------------------------------------------------------------------

    def run_check(self, kwargs):
        self.log("Checking for new bill emails...", level="INFO")

        try:
            emails = self._gmail.get_unread_bill_emails(self._gmail_label)
        except AuthError as e:
            self.log(f"Gmail auth error: {e}", level="ERROR")
            return
        except Exception as e:
            self.log(f"Failed to fetch emails from Gmail: {e}", level="ERROR")
            return

        if not emails:
            self.log("No unread emails found.", level="INFO")
            return

        self.log(f"Found {len(emails)} unread email(s).", level="INFO")

        processed = 0
        for email_data in emails:
            try:
                if self._process_single_email(email_data):
                    processed += 1
            except Exception as e:
                self.log(
                    f"Unhandled error processing email "
                    f"'{email_data.get('subject')}' from '{email_data.get('sender')}': {e}",
                    level="ERROR",
                )

        self.log(f"Check complete. Sent {processed} webhook(s).", level="INFO")

    # ------------------------------------------------------------------
    # Per-email processing
    # ------------------------------------------------------------------

    def _process_single_email(self, email_data: dict) -> bool:
        """
        Process one email. Returns True if a webhook was sent, False otherwise.
        Raises on unrecoverable errors (caught by caller).
        """
        message_id = email_data["message_id"]
        sender = email_data["sender"]
        subject = email_data["subject"]
        body = email_data["body_text"]

        # Step 1: look up bill config by sender
        config = self._find_bill_config(sender)
        if config is None:
            self.log(f"No bill config for sender: {sender!r}", level="WARNING")
            return False

        bill_name = config["bill_name"]

        # Step 2: skip if this exact message has already been processed
        if self._db.is_processed(message_id):
            self.log(f"Message {message_id} already processed, skipping.", level="DEBUG")
            return False

        # Step 3: extract amount
        amount = extract_amount(body, config["amount"]["pattern"])
        if amount is None:
            self.log(
                f"No amount found in email from {sender!r} (subject: {subject!r}). "
                "Check the amount pattern in bill_config.yaml.",
                level="WARNING",
            )
            return False

        # Step 4: extract and normalize due date
        due_date_raw = extract_due_date(body, config["due_date"]["pattern"])
        if due_date_raw is None:
            self.log(
                f"No due date found in email from {sender!r} (subject: {subject!r}). "
                "Check the due_date pattern in bill_config.yaml.",
                level="WARNING",
            )
            return False

        due_date = normalize_date(
            due_date_raw,
            config["due_date"]["input_format"],
            config["due_date"]["output_format"],
        )
        if due_date is None:
            self.log(
                f"Date normalization failed for {due_date_raw!r} "
                f"(input_format: {config['due_date']['input_format']!r}). "
                "Check the due_date formats in bill_config.yaml.",
                level="WARNING",
            )
            return False

        # Step 5: skip if we already notified HA about this bill for this due date
        if self._db.is_bill_notified(sender, due_date):
            self.log(
                f"Already notified for {bill_name} due {due_date}, skipping.",
                level="INFO",
            )
            # Still mark this specific message as processed so we don't revisit it
            self._db.record_processed(message_id, sender, subject)
            return False

        # Step 6: send webhook
        split_divisor = config.get("split_divisor", 1)
        split = round(float(amount) / split_divisor, 2)
        payload = {
            "amount": amount,
            "due_date": due_date,
            "bill_name": bill_name,
            "split": split,
        }

        response = requests.post(self._webhook_url, json=payload, timeout=10)
        response.raise_for_status()

        # Step 7: record state only after successful webhook delivery
        self._db.record_notified_bill(sender, due_date, amount, bill_name)
        self._db.record_processed(message_id, sender, subject)

        # Step 8: mark email as read so it isn't picked up again
        try:
            self._gmail.mark_as_read(message_id)
        except Exception as e:
            self.log(f"Failed to mark message {message_id} as read: {e}", level="WARNING")

        self.log(
            f"Webhook sent: {bill_name} — ${amount} due {due_date} "
            f"(split: ${split})",
            level="INFO",
        )
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_bill_config(self, sender: str) -> dict | None:
        """
        Find the first bill config whose sender_match is a case-insensitive
        substring of the full From header value.
        """
        sender_lower = sender.lower()
        for cfg in self._bill_configs:
            match_str = cfg.get("sender_match", "").lower()
            if match_str and match_str in sender_lower:
                return cfg
        return None

    @staticmethod
    def _resolve(base_dir: str, path: str) -> str:
        """Resolve a path relative to the AppDaemon apps base directory."""
        if os.path.isabs(path):
            return path
        # apps.yaml paths are relative to the appdaemon/apps/ directory
        apps_root = os.path.dirname(base_dir)
        return os.path.join(apps_root, path)
