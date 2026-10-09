"""Create per-machine secrets without printing them or overwriting configuration."""
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
password = secrets.token_hex(24)
token = secrets.token_urlsafe(36)
content = (root / '.env.example').read_text().replace('replace-with-random-password', password)
content = content.replace('replace-with-at-least-32-random-characters', token)
try:
    fd = os.open(root / '.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit('.env already exists; left unchanged.')
with os.fdopen(fd, 'w') as file:
    file.write(content)
print('Created .env with unique database and API credentials. Keep this file private.')
