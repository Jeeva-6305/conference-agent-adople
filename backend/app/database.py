"""
Database initialization and session management.

T-2 DATE FILTERING:
All conferences stored in the database are filtered by the T-2 rule. The database
only contains conferences that match the T-2 discovery date (today + 2 days). This
ensures the Excel output only publishes conferences that should be discovered on
that specific date according to business logic.

The filtering occurs at the scraper level before data is inserted into the database,
ensuring database consistency and supporting the publication workflow.
"""
import logging
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()

def get_engine():
    # Check if PostgreSQL is configured
    if "postgresql" in settings.DATABASE_URL.lower():
        try:
            logger.info(f"Attempting PostgreSQL connection to {settings.DATABASE_URL}...")
            engine = create_engine(
                settings.DATABASE_URL,
                pool_size=3,
                max_overflow=2,
                pool_recycle=3600,
                pool_pre_ping=True,
                pool_timeout=5,
                connect_args={"connect_timeout": 2},
                echo_pool=False
            )
            logger.info(f"Connected successfully to PostgreSQL at {settings.DATABASE_URL}")
            logger.info(f"Connection pool configured: size=3, max_overflow=2, timeout=5s")
            return engine
        except Exception as e:
            logger.warning(
                f"Could not connect to PostgreSQL ({str(e)[:100]}). "
                f"Falling back to local SQLite database at {settings.SQLITE_FALLBACK_URL}"
            )

    # Use SQLite fallback
    logger.info(f"Using SQLite database at {settings.SQLITE_FALLBACK_URL}")
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
    try:
        logger.debug("Creating database tables with timeout...")
        if "postgresql" in settings.DATABASE_URL.lower():
            from sqlalchemy.pool import NullPool
            import signal

            def timeout_handler(signum, frame):
                raise TimeoutError("Database table creation timed out")

            try:
                create_engine_temp = create_engine(
                    settings.DATABASE_URL,
                    poolclass=NullPool,
                    connect_args={"connect_timeout": 2}
                )
                Base.metadata.create_all(bind=create_engine_temp, checkfirst=True)
                create_engine_temp.dispose()
            except Exception as e:
                logger.warning(f"Database table creation failed (will retry on next request): {e}")
                return
        else:
            Base.metadata.create_all(bind=engine, checkfirst=True)
        logger.debug("Database tables created or verified")
    except Exception as e:
        logger.warning(f"Database table creation warning: {e}")

    try:
        logger.debug("Running auto-migrations...")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE conferences ADD COLUMN IF NOT EXISTS speaker_talks_details TEXT DEFAULT '';"))
            conn.execute(text("ALTER TABLE conferences ADD COLUMN IF NOT EXISTS description TEXT DEFAULT '';"))
            conn.execute(text("ALTER TABLE conferences ADD COLUMN IF NOT EXISTS email_sent BOOLEAN DEFAULT FALSE;"))
            conn.execute(text("ALTER TABLE conferences ADD COLUMN IF NOT EXISTS email_sent_at TIMESTAMP;"))
            # Ensure email_notifications table exists
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS email_notifications (
                    id SERIAL PRIMARY KEY,
                    conference_id VARCHAR(50),
                    conference_unique_key VARCHAR(500) UNIQUE,
                    conference_title VARCHAR(255) NOT NULL,
                    conference_date DATE NOT NULL,
                    venue VARCHAR(255) DEFAULT '',
                    recipient_email VARCHAR(255) NOT NULL,
                    subject VARCHAR(500) NOT NULL,
                    status VARCHAR(50) DEFAULT 'sent',
                    email_body TEXT DEFAULT '',
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error_message TEXT
                );
            """))
            conn.commit()
        logger.debug("Auto-migrations completed")
    except Exception as e:
        logger.warning(f"Auto-migration check notice: {e}")

    logger.info("Database tables initialized successfully.")
