"""
connect_gmail.py — Interactive Google OAuth Setup for JARVIS Gmail Integration.

This script sets up Google OAuth2 credentials to give JARVIS full Gmail access
(reading unread emails, thread inspection, sending, drafting, and search).

Usage:
    python scripts/connect_gmail.py
"""
import os
import sys
import json
import asyncio
from pathlib import Path

# Add backend directory to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "apps" / "backend"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BASE_DIR))

from google_auth_oauthlib.flow import InstalledAppFlow
from modules.security.credential_vault import CredentialVault
import aiohttp

# Gmail full access scopes needed for reading, drafting, sending, and searching
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose"
]


def run_oauth_flow():
    print("=" * 60)
    print("       JARVIS GMAIL FULL ACCESS SETUP WIZARD")
    print("=" * 60)
    print("\nTo connect Gmail, you will need a Google Cloud OAuth Client ID.")
    print("If you already downloaded 'credentials.json' (OAuth Client secret),")
    print("place it in 'apps/backend/' or enter Client ID & Secret below.\n")

    credentials_json_path = BASE_DIR / "credentials.json"
    client_secrets_file = None

    if credentials_json_path.exists():
        print(f"[+] Found credentials.json at: {credentials_json_path}")
        client_secrets_file = str(credentials_json_path)
        flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
    else:
        client_id = os.environ.get("GMAIL_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID")
        client_secret = os.environ.get("GMAIL_CLIENT_SECRET") or os.environ.get("GOOGLE_CLIENT_SECRET")

        if not client_id or not client_secret:
            print("Enter your Google Cloud OAuth Client credentials:")
            client_id = input("Google Client ID: ").strip()
            client_secret = input("Google Client Secret: ").strip()

        if not client_id or not client_secret:
            print("[-] Error: Client ID and Secret cannot be empty.")
            return False

        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/"]
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    print("\n[+] Opening browser for Google account authorization...")
    creds = flow.run_local_server(port=8080, prompt="consent", access_type="offline")

    if not creds:
        print("[-] Authorization failed or was cancelled.")
        return False

    print("\n[+] Authorization successful!")
    print(f"[+] Access Token acquired (expires in ~3600s)")
    if creds.refresh_token:
        print("[+] Refresh Token acquired (permanent connection)")
    else:
        print("[!] Note: Google did not return a new refresh token (already authorized).")

    # Store into encrypted CredentialVault
    vault = CredentialVault()
    token_dict = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri": creds.token_uri,
        "scopes": creds.scopes
    }
    vault.store_oauth_tokens("gmail", token_dict)
    print(f"[+] Credentials securely saved and encrypted into CredentialVault (database/credentials.db)!")

    # Optionally update .env
    env_file = BACKEND_DIR / ".env" if (BACKEND_DIR / ".env").exists() else BASE_DIR / ".env"
    if env_file.exists():
        try:
            content = env_file.read_text(encoding="utf-8")
            if "GMAIL_REFRESH_TOKEN=" not in content and creds.refresh_token:
                content += f"\nGMAIL_CLIENT_ID={creds.client_id}\nGMAIL_CLIENT_SECRET={creds.client_secret}\nGMAIL_REFRESH_TOKEN={creds.refresh_token}\n"
                env_file.write_text(content, encoding="utf-8")
                print("[+] Saved GMAIL_* OAuth variables to .env")
        except Exception:
            pass

    # Test reading inbox
    print("\n[+] Testing connection to Gmail API...")
    asyncio.run(verify_gmail_connection(creds.token))
    return True


async def verify_gmail_connection(access_token: str):
    url = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    profile = await resp.json()
                    email_addr = profile.get("emailAddress", "Unknown")
                    total_msgs = profile.get("messagesTotal", 0)
                    print(f"\n✅ SUCCESS: Connected to Gmail account: {email_addr}")
                    print(f"📊 Total Messages: {total_msgs}")
                    print("\nJARVIS is now fully connected to your Gmail!")
                    print("You can now say:")
                    print("  - 'JARVIS, check my unread emails on Gmail'")
                    print("  - 'JARVIS, search emails from boss on Gmail'")
                    print("  - 'JARVIS, send an email to user@example.com'")
                else:
                    err = await resp.text()
                    print(f"[-] Test failed ({resp.status}): {err}")
    except Exception as e:
        print(f"[-] Connection test error: {e}")


if __name__ == "__main__":
    run_oauth_flow()
