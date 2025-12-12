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
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Add project root to Python path so we can import pkg and app modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Now import the Base and models
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
        print("❌ ERROR: Please set DATABASE_URL environment variable (Railway provides this) and re-run.")
        print("Example: export DATABASE_URL='postgresql://...'")
        sys.exit(2)

    sync_url = normalize_database_url(database_url)
    
    # Mask password in log output
    display_url = sync_url
    if '@' in sync_url:
        # Format: postgresql://user:pass@host:port/db
        parts = sync_url.split('@')
        if ':' in parts[0]:
            user_pass = parts[0].split('://')[-1]
            if ':' in user_pass:
                user = user_pass.split(':')[0]
                display_url = sync_url.replace(user_pass, f"{user}:***")
    
    print(f"🔗 Using database URL: {display_url}")

    try:
        print("\n📦 Creating SQLAlchemy engine...")
        engine = create_engine(sync_url, echo=True)
        
        print("\n🧪 Testing database connection...")
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✅ Connected to: {version[:80]}...")
        
        print("\n🗑️  Dropping old tables (if any)...")
        with engine.begin() as conn:
            # Drop in reverse order to handle foreign keys
            conn.execute(text("DROP TABLE IF EXISTS messages CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS conversations CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS users CASCADE"))
            print("✅ Old tables dropped")
        
        print("\n🔨 Creating tables from SQLAlchemy metadata...")
        Base.metadata.create_all(bind=engine)
        print("✅ Tables created successfully!")
        
        print("\n📊 Verifying tables exist...")
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name
            """))
            tables = [row[0] for row in result]
            if tables:
                print(f"✅ Tables in database: {', '.join(tables)}")
            else:
                print("⚠️  No tables found in public schema")
        
        print("\n🎉 SUCCESS! Database tables are ready.")
        
    except SQLAlchemyError as e:
        print(f"\n❌ SQLAlchemy error: {e}")
        raise
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        raise


if __name__ == '__main__':
    main()
