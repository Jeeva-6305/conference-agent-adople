import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()

def get_engine():
    # Try PostgreSQL first
    try:
        engine = create_engine(
            settings.DATABASE_URL,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3} if "postgresql" in settings.DATABASE_URL else {}
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info(f"Connected successfully to PostgreSQL at {settings.DATABASE_URL}")
        return engine
    except Exception as e:
        logger.warning(
            f"Could not connect to PostgreSQL ({e}). "
            f"Falling back to local SQLite database at {settings.SQLITE_FALLBACK_URL}"
        )
        return create_engine(
            settings.SQLITE_FALLBACK_URL,
            connect_args={"check_same_thread": False}
        )

engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE conferences ADD COLUMN IF NOT EXISTS speaker_talks_details TEXT DEFAULT '';"))
            conn.execute(text("ALTER TABLE conferences ADD COLUMN IF NOT EXISTS description TEXT DEFAULT '';"))
            conn.commit()
    except Exception as e:
        logger.debug(f"Auto-migration check notice: {e}")
    logger.info("Database tables initialized successfully.")
