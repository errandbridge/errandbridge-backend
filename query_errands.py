from __future__ import annotations
from sqlalchemy import create_engine, text
engine = create_engine("sqlite:////Users/solopayne/Errandbridge-Project/errandbridge-backend/errandbridge.db")
with engine.connect() as conn:
    res = conn.execute(text("SELECT id, status, user_id, pilot_id FROM errands"))
    for row in res:
        print(row)
