import os
import json
import secrets
import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()
    return f'{salt}:{digest}'


def verify_password(password, stored):
    try:
        salt, _ = stored.split(':', 1)
        return hmac.compare_digest(hash_password(password, salt), stored)
    except (ValueError, TypeError, AttributeError):
        return False


@dataclass
class Settings:
    demo: bool
    database_url: str
    secret: str
    secure_cookie: bool
    stale_seconds: int
    users: dict
    sample_data: bool = False

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / '.env')
        demo = os.getenv('MONITOR_DEMO', 'true').lower() == 'true'
        if demo:
            users = {
                'engineer': {'password_hash': hash_password('demo-engineer'), 'role': 'engineer', 'machines': ['*']},
                'operator': {'password_hash': hash_password('demo-operator'), 'role': 'operator', 'machines': ['BOT-01', 'LAB-02', 'PKG-03']},
            }
            # Deliberately separate from any real database configuration.
            return cls(True, f'sqlite:///{ROOT / "demo-v2.db"}', secrets.token_urlsafe(48), False, 120, users)
        secret = os.environ.get('MONITOR_SESSION_SECRET', '')
        if len(secret) < 32 or 'CHANGE_ME' in secret:
            raise RuntimeError('Set MONITOR_SESSION_SECRET to a random secret of at least 32 characters.')
        url = os.environ['MONITOR_DATABASE_URL']
        if not url.startswith('mysql+pymysql://'):
            raise RuntimeError('Production mode expects a mysql+pymysql database URL.')
        users_path = Path(os.environ.get('MONITOR_USERS_FILE', 'users.json'))
        if not users_path.is_absolute():
            users_path = ROOT / users_path
        users = json.loads(users_path.read_text(encoding='utf-8'))
        if not isinstance(users, dict) or not users:
            raise RuntimeError('At least one configured account is required.')
        for name, user in users.items():
            if user.get('role') not in ('operator', 'supervisor', 'engineer', 'admin') or not isinstance(user.get('machines'), list) or not isinstance(user.get('password_hash'), str):
                raise RuntimeError(f'Invalid user configuration: {name}')
        stale = int(os.getenv('MONITOR_STALE_SECONDS', '120'))
        if stale < 1:
            raise RuntimeError('MONITOR_STALE_SECONDS must be positive.')
        return cls(False, url, secret, os.getenv('MONITOR_SECURE_COOKIE', 'true').lower() == 'true', stale, users, os.getenv('MONITOR_SAMPLE_DATA', 'false').lower() == 'true')
