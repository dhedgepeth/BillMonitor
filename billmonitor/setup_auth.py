"""
setup_auth.py — One-time OAuth2 token generation for BillMonitor.

Run this script ONCE on your desktop (Mac/Linux/Windows) to authorize
the app and generate token.json. Then copy token.json (and credentials.json)
to the AppDaemon apps directory on your Raspberry Pi.

Usage:
    python setup_auth.py --credentials credentials.json --token-output token.json

Requirements (install locally, not needed on the Pi):
    pip install google-auth-oauthlib
"""

import argparse
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print(
        "ERROR: google-auth-oauthlib is not installed.\n"
        "Run:  pip install google-auth-oauthlib"
    )
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def run_oauth_flow(credentials_path: str, token_output_path: str) -> None:
    print(f"Loading credentials from: {credentials_path}")
    print("A browser window will open. Log in with the Gmail account that receives your bills.")
    print("Grant the requested permission (read-only Gmail access).\n")

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(token_output_path, "w") as f:
        f.write(creds.to_json())

    print(f"\nSuccess! Token written to: {token_output_path}")
    print("\nNext steps:")
    print(f"  1. Copy '{token_output_path}' to your Pi at:")
    print(f"       /config/appdaemon/apps/billmonitor/token.json")
    print(f"  2. Copy '{credentials_path}' to:")
    print(f"       /config/appdaemon/apps/billmonitor/credentials.json")
    print()
    print("IMPORTANT: In Google Cloud Console, set your OAuth consent screen to")
    print("  'In production' (not 'Testing') to prevent the token expiring after 7 days.")
    print("  Settings & Services -> OAuth consent screen -> Publishing status -> Publish App")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a Gmail OAuth2 token for BillMonitor."
    )
    parser.add_argument(
        "--credentials",
        default="credentials.json",
        help="Path to credentials.json downloaded from Google Cloud Console (default: credentials.json)",
    )
    parser.add_argument(
        "--token-output",
        default="token.json",
        help="Where to write the generated token.json (default: token.json)",
    )
    args = parser.parse_args()
    run_oauth_flow(args.credentials, args.token_output)


if __name__ == "__main__":
    main()
