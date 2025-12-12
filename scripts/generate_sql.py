"""Generate SQL CREATE TABLE statements from SQLAlchemy models.

This outputs pure SQL that you can copy/paste into Railway's Postgres SQL console.

Usage:
    python scripts/generate_sql.py > create_tables.sql
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine
from sqlalchemy.schema import CreateTable

# Import Base and all models
from pkg.db_util.sql_alchemy.declarative_base import Base
from app.chat.repository.sql_schema.conversation import ConversationModel, MessageModel
from app.user.repository.sql_schema.user import UserModel


def generate_sql():
    """Generate CREATE TABLE SQL for all models."""
    
    # Use a dummy PostgreSQL dialect engine (doesn't need real connection)
    engine = create_engine("postgresql://dummy", strategy='mock', executor=lambda sql, *_: None)
    
    print("-- ============================================")
    print("-- Railway Postgres Table Creation SQL")
    print("-- ============================================")
    print("-- Copy and paste this into Railway SQL console")
    print("-- ============================================\n")
    
    print("-- Drop existing tables (in reverse order for foreign keys)")
    print("DROP TABLE IF EXISTS messages CASCADE;")
    print("DROP TABLE IF EXISTS conversations CASCADE;")
    print("DROP TABLE IF EXISTS users CASCADE;\n")
    
    # Generate CREATE TABLE statements for each model
    for table in Base.metadata.sorted_tables:
        print(f"-- Creating table: {table.name}")
        create_stmt = str(CreateTable(table).compile(engine))
        print(create_stmt + ";")
        print()
    
    print("-- Create indexes")
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            # SQLAlchemy's CreateIndex would work here, but let's keep it simple
            columns = ', '.join([col.name for col in index.columns])
            index_name = index.name or f"ix_{table.name}_{columns.replace(', ', '_')}"
            print(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table.name} ({columns});")
    
    print("\n-- ============================================")
    print("-- Verify tables were created")
    print("-- ============================================")
    print("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;")


if __name__ == "__main__":
    generate_sql()
