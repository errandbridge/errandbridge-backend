from __future__ import annotations
import sqlalchemy
from sqlalchemy import create_engine

passwords = ["postgres", "root", "admin", "password", "123456", ""]
users = ["postgres", "solopayne"]
for u in users:
    for p in passwords:
        try:
            url = f"postgresql+psycopg://{u}:{p}@127.0.0.1:5432/postgres" if p else f"postgresql+psycopg://{u}@127.0.0.1:5432/postgres"
            engine = create_engine(url)
            engine.connect()
            print(f"SUCCESS: {u}:{p}")
        except Exception as e:
            pass

print("Done")
