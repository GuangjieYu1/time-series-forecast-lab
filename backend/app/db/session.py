from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database


engine = create_engine(get_settings().sqlite_url, connect_args={"check_same_thread": False})
bootstrap_database(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
