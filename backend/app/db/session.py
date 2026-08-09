from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    echo=settings.debug,
)


def _add_missing_columns() -> None:
    """Lightweight migrations for columns added after initial schema creation."""
    import sqlite3

    if not settings.database_url.startswith("sqlite"):
        return
    db_path = settings.database_url.replace("sqlite:///", "")
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        item_cols = {row[1] for row in cur.execute("PRAGMA table_info(item)").fetchall()}
        if "category" not in item_cols:
            cur.execute("ALTER TABLE item ADD COLUMN category VARCHAR(60)")
        recipe_cols = {row[1] for row in cur.execute("PRAGMA table_info(recipesuggestion)").fetchall()}
        if "meal_type" not in recipe_cols:
            cur.execute("ALTER TABLE recipesuggestion ADD COLUMN meal_type VARCHAR(20)")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[db] Migration skipped: {e}")


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def get_session() -> Session:
    with Session(engine) as session:
        yield session


def SessionLocal() -> Session:
    """Context-manager-friendly session factory for background/agent use.

    Usage: with SessionLocal() as session: ...
    """
    return Session(engine)
