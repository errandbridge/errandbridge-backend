# Script to reset admin password using app's own hash_password

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from sqlalchemy import create_engine, text
from auth import hash_password

# Force use of sync driver for direct DB update
raw_url = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/errandbridge"
)
if raw_url.startswith("postgresql+asyncpg://"):
    db_url = raw_url.replace("postgresql+asyncpg://", "postgresql://")
else:
    db_url = raw_url
engine = create_engine(db_url)

email = "admin@errandbridge.com"
new_password = "AdminReset2026!"

with engine.begin() as conn:
    # Print current hash before update
    before = conn.execute(
        text("SELECT password_hash FROM users WHERE email=:email"), {"email": email}
    ).fetchone()
    print(f"Before update: {before}")
    hashed = hash_password(new_password)
    result = conn.execute(
        text("""
        UPDATE users SET password_hash=:hashed WHERE email=:email
    """),
        {"hashed": hashed, "email": email},
    )
    print(f"Updated {result.rowcount} row(s) for {email}")
    # Print hash after update
    after = conn.execute(
        text("SELECT password_hash FROM users WHERE email=:email"), {"email": email}
    ).fetchone()
    print(f"After update: {after}")
