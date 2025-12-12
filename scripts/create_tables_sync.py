"""One-off helper to create database tables using SQLAlchemy sync engine.

Usage (locally):

    # export the DATABASE_URL from Railway or set it inline
    export DATABASE_URL="<your-railway-database-url>"
    python scripts/create_tables_sync.py

Notes:
- If your DATABASE_URL is in the `postgresql+asyncpg://...` form, the script will convert
  it to a sync URL (`postgresql://...`) automatically.
- This script imports your project's SQLAlchemy `Base` and model modules so SQLAlchemy
  can emit the correct CREATE TABLE statements.
- Run this from your project root in the virtualenv used by the app.
"""

import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

# Adjust the import below if your declarative Base is at a different path
try:
    from pkg.db_util.sql_alchemy.declarative_base import Base
except Exception as e:
    print("Error importing Base from pkg.db_util.sql_alchemy.declarative_base:", e)
    raise

# Import all model modules so tables are registered in Base.metadata
# Add any other modules that define models if not imported here
try:
    # Chat and user models
    from app.chat.repository.sql_schema import conversation as _conv  # noqa: F401
    from app.user.repository.sql_schema import user as _user  # noqa: F401
except Exception:
    # If your project structure differs, ignore import errors but warn
    print("Warning: could not import model modules automatically; ensure models are imported so metadata is complete.")


def normalize_database_url(url: str) -> str:
    """Convert async SQLAlchemy URL (postgresql+asyncpg://) to a sync driver URL (postgresql://)."""
    if not url:
        raise ValueError("DATABASE_URL not provided")
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    # Common shorthand (postgres://) is accepted by many drivers; return as-is
    return url


def main():
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not database_url:
        print("Please set DATABASE_URL environment variable (Railway provides this) and re-run.")
        sys.exit(2)

    sync_url = normalize_database_url(database_url)
    print("Using database URL:", sync_url.replace(os.environ.get('POSTGRES_PASSWORD',''), '***') if os.environ.get('POSTGRES_PASSWORD') else sync_url)

    try:
        engine = create_engine(sync_url, echo=True)
        print("Creating tables from metadata...")
        Base.metadata.create_all(bind=engine)
        print("Table creation complete.")
    except SQLAlchemyError as e:
        print("SQLAlchemy error during create_all():", e)
        raise
    except Exception as e:
        print("Unexpected error:", e)
        raise


if __name__ == '__main__':
    main()
