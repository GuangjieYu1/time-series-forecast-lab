from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.db.models import Base
from app.db.schema_compat import ensure_schema_compatibility


engine = create_engine(get_settings().sqlite_url, connect_args={"check_same_thread": False})
Base.metadata.create_all(bind=engine)
ensure_schema_compatibility(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
