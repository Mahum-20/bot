import os
import time
import hmac
import hashlib
import secrets
import sqlite3
import logging
from typing import Dict, Optional, Tuple, Any
from cryptography.fernet import Fernet

logger = logging.getLogger("SecurityVault")

VAULT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(VAULT_DIR, "bot_vault.db")
KEY_PATH = os.path.join(VAULT_DIR, "vault.key")

PBKDF2_ITERATIONS = 600_000
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 900
SESSION_DURATION_SECONDS = 7 * 24 * 3600

def _get_or_create_master_key() -> bytes:
    if os.path.exists(KEY_PATH):
        try:
            with open(KEY_PATH, "rb") as f:
                key = f.read().strip()
                if len(key) == 44:
                    return key
        except Exception as e:
            logger.error(f"Error reading vault master key: {e}")

    new_key = Fernet.generate_key()
    try:
        with open(KEY_PATH, "wb") as f:
            f.write(new_key)
        try:
            os.chmod(KEY_PATH, 0o600)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Failed to write vault master key: {e}")
    return new_key

_FERNET_CIPHER: Optional[Fernet] = None

def _get_cipher() -> Fernet:
    global _FERNET_CIPHER
    if _FERNET_CIPHER is None:
        key = _get_or_create_master_key()
        _FERNET_CIPHER = Fernet(key)
    return _FERNET_CIPHER

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_vault():
    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                failed_attempts INTEGER DEFAULT 0,
                lockout_until REAL DEFAULT 0.0,
                created_at REAL NOT NULL,
                last_login REAL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_sessions (
                token_hash TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                ip_address TEXT,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS exchange_credentials (
                exchange TEXT PRIMARY KEY,
                encrypted_api_key TEXT NOT NULL,
                encrypted_api_secret TEXT NOT NULL,
                masked_key TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'PAPER',
                updated_at REAL NOT NULL
            )
        ''')
        conn.commit()

        # 1. RBAC Schema Migration: add role column to admin_users and active_sessions if missing
        try:
            cursor.execute("ALTER TABLE admin_users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE active_sessions ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        # 2. Ensure admin account 'mahum' exists with role 'admin'
        cursor.execute("SELECT id FROM admin_users WHERE LOWER(username) = 'mahum'")
        admin_row = cursor.fetchone()
        if not admin_row:
            default_user = "mahum"
            default_pass = "A1sdf234?"
            salt = secrets.token_hex(16)
            pwd_hash = hashlib.pbkdf2_hmac(
                "sha256",
                default_pass.encode("utf-8"),
                salt.encode("utf-8"),
                PBKDF2_ITERATIONS
            ).hex()
            cursor.execute('''
                INSERT INTO admin_users (username, salt, password_hash, role, failed_attempts, lockout_until, created_at)
                VALUES (?, ?, ?, 'admin', 0, 0.0, ?)
            ''', (default_user, salt, pwd_hash, time.time()))
            conn.commit()
            logger.info("Admin user 'mahum' initialized with role 'admin'.")
        else:
            cursor.execute("UPDATE admin_users SET role = 'admin' WHERE LOWER(username) = 'mahum'")
            conn.commit()

        # 3. Ensure viewer account 'user' exists with password 'user1234' and role 'user'
        cursor.execute("SELECT id FROM admin_users WHERE LOWER(username) = 'user'")
        user_row = cursor.fetchone()
        salt_user = secrets.token_hex(16)
        pwd_hash_user = hashlib.pbkdf2_hmac(
            "sha256",
            b"user1234",
            salt_user.encode("utf-8"),
            PBKDF2_ITERATIONS
        ).hex()
        if not user_row:
            cursor.execute('''
                INSERT INTO admin_users (username, salt, password_hash, role, failed_attempts, lockout_until, created_at)
                VALUES (?, ?, ?, 'user', 0, 0.0, ?)
            ''', ("user", salt_user, pwd_hash_user, time.time()))
            conn.commit()
            logger.info("Viewer user 'user' initialized with role 'user'.")
        else:
            cursor.execute('''
                UPDATE admin_users 
                SET salt = ?, password_hash = ?, role = 'user', failed_attempts = 0, lockout_until = 0.0
                WHERE LOWER(username) = 'user'
            ''', (salt_user, pwd_hash_user))
            conn.commit()
            logger.info("Viewer user 'user' credentials and role refreshed.")


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

def authenticate_user(username: str, password: str, client_ip: str = "", requested_role: Optional[str] = None) -> Tuple[bool, Optional[str], str, Optional[str]]:
    clean_user = username.strip().lower()
    now = time.time()

    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admin_users WHERE LOWER(username) = ?", (clean_user,))
        user_row = cursor.fetchone()

        if not user_row:
            dummy_salt = "0" * 32
            hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), dummy_salt.encode("utf-8"), PBKDF2_ITERATIONS)
            return False, None, "Invalid credentials.", None

        user_role = user_row["role"] if "role" in user_row.keys() and user_row["role"] else "admin"

        # Enforce RBAC separation at login: prevent logging in under mismatched role toggle
        if requested_role:
            clean_requested = requested_role.strip().lower()
            if clean_requested != user_role.lower():
                if clean_requested == "admin":
                    return False, None, "Access denied: Account does not have Administrator privileges.", None
                else:
                    return False, None, "Access denied: Administrator account cannot sign in under User role.", None

        lockout_until = user_row["lockout_until"]
        if lockout_until and now < lockout_until:
            remaining_mins = max(1, int((lockout_until - now) / 60))
            return False, None, f"Security Lockout: Too many failed attempts. Try again in {remaining_mins} minute(s).", None

        salt = user_row["salt"]
        stored_hash = user_row["password_hash"]
        computed_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            PBKDF2_ITERATIONS
        ).hex()

        if not hmac.compare_digest(computed_hash, stored_hash):
            new_attempts = user_row["failed_attempts"] + 1
            if new_attempts >= MAX_FAILED_ATTEMPTS:
                lock_time = now + LOCKOUT_DURATION_SECONDS
                cursor.execute(
                    "UPDATE admin_users SET failed_attempts = ?, lockout_until = ? WHERE id = ?",
                    (new_attempts, lock_time, user_row["id"])
                )
                conn.commit()
                return False, None, "Too many failed attempts. Account locked for 15 minutes.", None
            else:
                cursor.execute(
                    "UPDATE admin_users SET failed_attempts = ? WHERE id = ?",
                    (new_attempts, user_row["id"])
                )
                conn.commit()
                remaining = MAX_FAILED_ATTEMPTS - new_attempts
                return False, None, f"Invalid credentials. ({remaining} attempt(s) remaining)", None

        cursor.execute(
            "UPDATE admin_users SET failed_attempts = 0, lockout_until = 0.0, last_login = ? WHERE id = ?",
            (now, user_row["id"])
        )

        raw_token = secrets.token_hex(32)
        token_digest = hash_token(raw_token)
        expires_at = now + SESSION_DURATION_SECONDS

        cursor.execute("DELETE FROM active_sessions WHERE expires_at < ?", (now,))
        cursor.execute('''
            INSERT INTO active_sessions (token_hash, username, role, ip_address, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (token_digest, user_row["username"], user_role, client_ip, now, expires_at))
        conn.commit()

        return True, raw_token, "Authentication successful.", user_role

def get_session_info(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token or len(token) < 32:
        return None
    now = time.time()
    token_digest = hash_token(token)

    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username, role, expires_at FROM active_sessions WHERE token_hash = ?",
            (token_digest,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        if now > row["expires_at"]:
            cursor.execute("DELETE FROM active_sessions WHERE token_hash = ?", (token_digest,))
            conn.commit()
            return None

        role = row["role"] if "role" in row.keys() and row["role"] else "admin"
        return {
            "username": row["username"],
            "role": role
        }

def verify_session_token(token: Optional[str]) -> bool:
    return get_session_info(token) is not None

def revoke_session_token(token: Optional[str]) -> bool:
    if not token:
        return False
    token_digest = hash_token(token)
    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM active_sessions WHERE token_hash = ?", (token_digest,))
        conn.commit()
        return True

def logout_all_sessions():
    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM active_sessions")
        conn.commit()

def mask_key(key: str) -> str:
    clean = key.strip()
    if not clean:
        return ""
    if len(clean) <= 8:
        return "********"
    return clean[:4] + "********" + clean[-4:]

def save_exchange_credentials(exchange: str, api_key: str, api_secret: str, mode: str = "PAPER") -> bool:
    cipher = _get_cipher()
    enc_key = cipher.encrypt(api_key.strip().encode("utf-8")).decode("utf-8")
    enc_secret = cipher.encrypt(api_secret.strip().encode("utf-8")).decode("utf-8")
    masked = mask_key(api_key)

    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO exchange_credentials (exchange, encrypted_api_key, encrypted_api_secret, masked_key, mode, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange) DO UPDATE SET
                encrypted_api_key = excluded.encrypted_api_key,
                encrypted_api_secret = excluded.encrypted_api_secret,
                masked_key = excluded.masked_key,
                mode = excluded.mode,
                updated_at = excluded.updated_at
        ''', (exchange.upper(), enc_key, enc_secret, masked, mode.upper(), time.time()))
        conn.commit()
        logger.info(f"Credentials for {exchange.upper()} encrypted and saved to bot_vault.db.")
        return True

def load_exchange_credentials(exchange: str = "BINANCE") -> Dict[str, str]:
    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM exchange_credentials WHERE exchange = ?", (exchange.upper(),))
        row = cursor.fetchone()
        if not row:
            return {"api_key": "", "api_secret": "", "mode": "PAPER", "masked_key": ""}

        cipher = _get_cipher()
        try:
            dec_key = cipher.decrypt(row["encrypted_api_key"].encode("utf-8")).decode("utf-8")
            dec_secret = cipher.decrypt(row["encrypted_api_secret"].encode("utf-8")).decode("utf-8")
            return {
                "api_key": dec_key,
                "api_secret": dec_secret,
                "mode": row["mode"],
                "masked_key": row["masked_key"]
            }
        except Exception as e:
            logger.error(f"Failed to decrypt credentials for {exchange}: {e}")
            return {"api_key": "", "api_secret": "", "mode": "PAPER", "masked_key": ""}

def get_safe_exchange_status(exchange: str = "BINANCE") -> Dict[str, Any]:
    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT masked_key, mode, updated_at FROM exchange_credentials WHERE exchange = ?", (exchange.upper(),))
        row = cursor.fetchone()
        if not row or not row["masked_key"]:
            return {
                "configured": False,
                "mode": "PAPER",
                "masked_key": "",
                "secret_configured": False
            }
        return {
            "configured": bool(row["masked_key"]),
            "mode": row["mode"],
            "masked_key": row["masked_key"],
            "secret_configured": True,
            "updated_at": row["updated_at"]
        }

init_vault()

