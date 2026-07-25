from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def run_migrations() -> None:
    """Add columns that didn't exist in earlier schema versions."""
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(runs)"))}
        if "log" not in existing:
            conn.execute(text("ALTER TABLE runs ADD COLUMN log TEXT"))
            conn.commit()
        if "target_id" not in existing:
            conn.execute(text("ALTER TABLE runs ADD COLUMN target_id INTEGER"))
            conn.commit()
        if "target_label" not in existing:
            conn.execute(text("ALTER TABLE runs ADD COLUMN target_label TEXT"))
            conn.commit()

        target_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(targets)"))}
        if target_cols:  # skip on a fresh DB, where create_all already made them
            # Defaults match the pre-existing behaviour: substyles on (so a broad
            # pick keeps working) and unclassified artists allowed through, which
            # is what the old genre check did.
            if "genre_include_substyles" not in target_cols:
                conn.execute(text("ALTER TABLE targets ADD COLUMN genre_include_substyles BOOLEAN DEFAULT 1 NOT NULL"))
                conn.commit()
            if "genre_include_unclassified" not in target_cols:
                conn.execute(
                    text("ALTER TABLE targets ADD COLUMN genre_include_unclassified BOOLEAN DEFAULT 1 NOT NULL")
                )
                conn.commit()
            if "genre_scan" not in target_cols:
                conn.execute(text("ALTER TABLE targets ADD COLUMN genre_scan TEXT DEFAULT '' NOT NULL"))
                conn.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
