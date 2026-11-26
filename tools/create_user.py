"""Run from project root: python -m tools.create_user"""
import json
import getpass
from pathlib import Path
from app.config import hash_password

path = Path('users.json')
users = json.loads(path.read_text()) if path.exists() else {}
name = input('Username: ').strip()
role = input('Role (operator/supervisor/engineer/admin): ').strip()
machines = [x.strip() for x in input('Allowed machine IDs, comma separated (* for all): ').split(',') if x.strip()]
if not name or role not in ('operator', 'supervisor', 'engineer', 'admin') or not machines:
    raise SystemExit('Invalid username, role or machine scope.')
if name in users:
    raise SystemExit('User already exists. Edit the configuration deliberately to replace it.')
password = getpass.getpass('Password (at least 12 characters): ')
if len(password) < 12 or password != getpass.getpass('Repeat password: '):
    raise SystemExit('Passwords did not match or were too short.')
users[name] = {'password_hash': hash_password(password), 'role': role, 'machines': machines}
path.write_text(json.dumps(users, indent=2) + '\n', encoding='utf-8')
try:
    path.chmod(0o600)
except OSError:
    pass
print(f'Account {name} added to {path}. Restart the service to load it.')
