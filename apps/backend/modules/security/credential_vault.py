"""
credential_vault.py — Encrypted Vault for Third-Party Social Media Credentials & Sessions.

Provides secure storage and lifecycle management for OAuth2 tokens (Gmail, LinkedIn)
and Playwright browser session states (WhatsApp, Instagram).
All sensitive data is encrypted at rest using AES-128-CBC/HMAC via Fernet.
"""
import os
import json
import time
import base64
import sqlite3
import threading
import logging
from typing import Any, Dict, Optional
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("JARVIS.CredentialVault")


class CredentialVault:
    """
    Thread-safe encrypted store for social platform credentials, OAuth tokens,
    session states, and kill switches.
    """

    def __init__(self, db_path: Optional[str] = None, vault_key: Optional[str] = None):
        if db_path is None:
            from config.settings import DATA_DIR
            db_path = os.path.join(DATA_DIR, "credentials.db")
            
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.db_path = db_path
        self._lock = threading.Lock()
        self._fernet = self._init_fernet(vault_key)
        self._init_db()
        logger.info(f"CredentialVault initialized using database: {self.db_path}")

    def _init_fernet(self, vault_key: Optional[str]) -> Fernet:
        """Derive or load encryption key for Fernet."""
        key = vault_key or os.environ.get("SOCIAL_VAULT_KEY") or os.environ.get("JARVIS_VAULT_KEY")
        if key:
            try:
                # Validate key
                key_bytes = key.encode("utf-8") if isinstance(key, str) else key
                return Fernet(key_bytes)
            except Exception as e:
                logger.warning(f"Invalid SOCIAL_VAULT_KEY provided: {e}. Falling back to key file.")

        # Key file in same directory as DB
        key_file = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), ".vault_key")
        if os.path.exists(key_file):
            try:
                with open(key_file, "rb") as f:
                    file_key = f.read().strip()
                return Fernet(file_key)
            except Exception as e:
                logger.error(f"Failed to read existing vault key file: {e}. Generating new key.")

        # Generate and persist key
        new_key = Fernet.generate_key()
        try:
            with open(key_file, "wb") as f:
                f.write(new_key)
            if hasattr(os, "chmod"):
                try:
                    os.chmod(key_file, 0o600)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Could not persist vault key to file: {e}")

        return Fernet(new_key)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS credentials (
                        platform TEXT PRIMARY KEY,
                        cred_type TEXT NOT NULL,
                        encrypted_data BLOB NOT NULL,
                        expires_at REAL,
                        updated_at REAL NOT NULL,
                        meta TEXT,
                        killswitch INTEGER DEFAULT 0
                    );
                """)
                conn.commit()
            finally:
                conn.close()

    def _encrypt(self, data: Dict[str, Any]) -> bytes:
        raw_json = json.dumps(data).encode("utf-8")
        return self._fernet.encrypt(raw_json)

    def _decrypt(self, encrypted_bytes: bytes) -> Dict[str, Any]:
        try:
            decrypted = self._fernet.decrypt(encrypted_bytes)
            return json.loads(decrypted.decode("utf-8"))
        except InvalidToken:
            logger.error("Failed to decrypt credentials: Invalid Token or altered key.")
            raise ValueError("Credential decryption failed — key mismatch or corrupted data.")
        except Exception as e:
            logger.error(f"Error parsing decrypted payload: {e}")
            raise

    # ── OAuth Operations ──────────────────────────────────────────────────────

    def store_oauth_tokens(
        self,
        platform: str,
        token_data: Dict[str, Any],
        expires_at: Optional[float] = None,
        meta: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Store OAuth2 token dictionary (access_token, refresh_token, scopes, etc.).
        """
        platform_norm = platform.strip().lower()
        enc = self._encrypt(token_data)
        meta_str = json.dumps(meta or {})
        now = time.time()
        
        if expires_at is None and "expires_at" in token_data:
            try:
                expires_at = float(token_data["expires_at"])
            except (ValueError, TypeError):
                expires_at = None
        elif expires_at is None and "expires_in" in token_data:
            try:
                expires_at = now + float(token_data["expires_in"])
            except (ValueError, TypeError):
                expires_at = None

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    INSERT INTO credentials (platform, cred_type, encrypted_data, expires_at, updated_at, meta, killswitch)
                    VALUES (?, 'oauth', ?, ?, ?, ?, 0)
                    ON CONFLICT(platform) DO UPDATE SET
                        cred_type = 'oauth',
                        encrypted_data = excluded.encrypted_data,
                        expires_at = excluded.expires_at,
                        updated_at = excluded.updated_at,
                        meta = excluded.meta;
                """, (platform_norm, enc, expires_at, now, meta_str))
                conn.commit()
                logger.info(f"OAuth tokens stored for platform: {platform_norm}")
                return True
            except Exception as e:
                logger.error(f"Failed to store OAuth tokens for {platform_norm}: {e}")
                return False
            finally:
                conn.close()

    def get_oauth_tokens(self, platform: str) -> Optional[Dict[str, Any]]:
        """Retrieve and decrypt OAuth tokens for a platform."""
        platform_norm = platform.strip().lower()
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT encrypted_data, cred_type FROM credentials WHERE platform = ?",
                    (platform_norm,)
                ).fetchone()
                if not row:
                    return None
                enc_data, cred_type = row
                if cred_type != "oauth":
                    logger.warning(f"Platform {platform_norm} credential is of type '{cred_type}', not 'oauth'")
                return self._decrypt(enc_data)
            except Exception as e:
                logger.error(f"Failed to get OAuth tokens for {platform_norm}: {e}")
                return None
            finally:
                conn.close()

    # ── Session State Operations (Playwright Cookies/LocalStorage) ────────────

    def store_session_state(
        self,
        platform: str,
        session_data: Dict[str, Any],
        meta: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Store Playwright storage_state (cookies + localStorage).
        """
        platform_norm = platform.strip().lower()
        enc = self._encrypt(session_data)
        meta_str = json.dumps(meta or {})
        now = time.time()

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    INSERT INTO credentials (platform, cred_type, encrypted_data, expires_at, updated_at, meta, killswitch)
                    VALUES (?, 'session', ?, NULL, ?, ?, 0)
                    ON CONFLICT(platform) DO UPDATE SET
                        cred_type = 'session',
                        encrypted_data = excluded.encrypted_data,
                        updated_at = excluded.updated_at,
                        meta = excluded.meta;
                """, (platform_norm, enc, now, meta_str))
                conn.commit()
                logger.info(f"Session state stored for platform: {platform_norm}")
                return True
            except Exception as e:
                logger.error(f"Failed to store session state for {platform_norm}: {e}")
                return False
            finally:
                conn.close()

    def get_session_state(self, platform: str) -> Optional[Dict[str, Any]]:
        """Retrieve and decrypt Playwright storage_state."""
        platform_norm = platform.strip().lower()
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT encrypted_data, cred_type FROM credentials WHERE platform = ?",
                    (platform_norm,)
                ).fetchone()
                if not row:
                    return None
                enc_data, cred_type = row
                return self._decrypt(enc_data)
            except Exception as e:
                logger.error(f"Failed to get session state for {platform_norm}: {e}")
                return None
            finally:
                conn.close()

    # ── Revocation, Status & Killswitch ───────────────────────────────────────

    def has_credentials(self, platform: str) -> bool:
        """Check if any valid credentials exist for the platform."""
        platform_norm = platform.strip().lower()
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT 1 FROM credentials WHERE platform = ?", (platform_norm,)
                ).fetchone()
                return bool(row)
            finally:
                conn.close()

    def revoke(self, platform: str) -> bool:
        """Delete stored credentials for a platform."""
        platform_norm = platform.strip().lower()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("DELETE FROM credentials WHERE platform = ?", (platform_norm,))
                conn.commit()
                logger.info(f"Revoked credentials for platform: {platform_norm}")
                return True
            except Exception as e:
                logger.error(f"Failed to revoke credentials for {platform_norm}: {e}")
                return False
            finally:
                conn.close()

    def set_killswitch(self, platform: str, enabled: bool) -> bool:
        """Toggle kill switch for a specific platform."""
        platform_norm = platform.strip().lower()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE credentials SET killswitch = ? WHERE platform = ?",
                    (1 if enabled else 0, platform_norm)
                )
                conn.commit()
                logger.info(f"Platform {platform_norm} killswitch set to: {enabled}")
                return True
            except Exception as e:
                logger.error(f"Failed to update killswitch for {platform_norm}: {e}")
                return False
            finally:
                conn.close()

    def is_killswitch_active(self, platform: str) -> bool:
        """Check if kill switch is active for platform."""
        platform_norm = platform.strip().lower()
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT killswitch FROM credentials WHERE platform = ?", (platform_norm,)
                ).fetchone()
                if row:
                    return bool(row[0])
                return False
            finally:
                conn.close()

    def get_connection_status(self, platform: str) -> Dict[str, Any]:
        """Return connection metadata without exposing decrypted secrets."""
        platform_norm = platform.strip().lower()
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT cred_type, expires_at, updated_at, meta, killswitch FROM credentials WHERE platform = ?",
                    (platform_norm,)
                ).fetchone()
                if not row:
                    return {
                        "platform": platform_norm,
                        "connected": False,
                        "status": "Not connected",
                        "cred_type": None,
                        "is_expired": False,
                        "killswitch": False,
                        "updated_at": None,
                    }

                cred_type, expires_at, updated_at, meta_str, killswitch = row
                meta = json.loads(meta_str) if meta_str else {}
                now = time.time()
                is_expired = (expires_at is not None and expires_at < now)
                
                status = "Connected"
                if killswitch:
                    status = "Paused (Killswitch Active)"
                elif is_expired:
                    status = "Expired"

                return {
                    "platform": platform_norm,
                    "connected": not is_expired and not bool(killswitch),
                    "raw_connected": True,
                    "status": status,
                    "cred_type": cred_type,
                    "expires_at": expires_at,
                    "is_expired": is_expired,
                    "killswitch": bool(killswitch),
                    "updated_at": updated_at,
                    "meta": meta
                }
            finally:
                conn.close()

    def get_all_statuses(self) -> Dict[str, Dict[str, Any]]:
        """Return connection statuses for all standard supported platforms."""
        standard_platforms = ["gmail", "whatsapp", "linkedin", "instagram"]
        results = {}
        for p in standard_platforms:
            results[p] = self.get_connection_status(p)
        return results
