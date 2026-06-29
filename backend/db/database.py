import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("JARVIS_DB_URL", "sqlite:///./database/jarvis_main.db")

# For sqlite: allow multithread connections
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    
    # Ensure database dir exists
    db_dir = os.path.dirname(DATABASE_URL.replace("sqlite:///./", "").replace("sqlite:///", ""))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
