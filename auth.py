"""
Authentication Interface Module
===============================
Delegates all credential verification, session management, and brute-force 
protection to the secure SQLite vault (vault.py).
Zero plaintext passwords or secrets stored in code or comments.
"""

from typing import Optional, Tuple, Dict, Any
import vault

def authenticate_user(username: str, password: str, client_ip: str = "", requested_role: Optional[str] = None) -> Tuple[bool, Optional[str], str, Optional[str]]:
    """Authenticates user via vault.py with role-based checks."""
    return vault.authenticate_user(username, password, client_ip, requested_role)

def verify_token(token: Optional[str]) -> bool:
    """Verifies unexpired session token in vault.db."""
    return vault.verify_session_token(token)

def get_session_info(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Retrieves session details (username, role) if token is valid."""
    return vault.get_session_info(token)

def invalidate_token(token: Optional[str]) -> bool:
    """Invalidates session token on logout."""
    return vault.revoke_session_token(token)

def logout_all_sessions():
    """Invalidates all sessions across the system."""
    vault.logout_all_sessions()

