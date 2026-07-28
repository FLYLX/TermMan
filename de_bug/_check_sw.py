import sys, json
sys.path.insert(0, "/app/backend")
from sqlmodel import Session, text
from app.core.db import engine

with Session(engine) as s:
    # Check installed_software table
    result = s.exec(text("SELECT name FROM sqlite_master WHERE type='table'")).all()
    tables = [r[0] for r in result]
    print("Tables:", [t for t in tables if "soft" in t.lower() or "install" in t.lower()])
    
    # Try to find and clear java records
    for t in tables:
        if "soft" in t.lower() or "install" in t.lower():
            rows = s.exec(text(f"SELECT * FROM {t} LIMIT 5")).all()
            print(f"\n{t}: {len(rows)} rows")
            for r in rows:
                print(f"  {r}")