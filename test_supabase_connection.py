#!/usr/bin/env python3
"""
Test Supabase connection with different hostname formats
Run: python test_supabase_connection.py
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Common Supabase hostname patterns to try
SUPABASE_REGIONS = [
    "us-east-1",
    "us-west-1", 
    "us-west-2",
    "eu-west-1",
    "eu-west-2",
    "eu-central-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-northeast-1",
]

async def test_connection(host, port, user, password, database):
    """Test PostgreSQL connection"""
    try:
        import asyncpg
        print(f"   Testing: {user}@{host}:{port}/{database}")
        
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                timeout=10.0,
            ),
            timeout=15.0
        )
        
        version = await conn.fetchval('SELECT version()')
        print(f"   ✅ SUCCESS! Connected to: {host}")
        print(f"   Database version: {version[:80]}...")
        await conn.close()
        return True
        
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False

async def main():
    print("=" * 70)
    print("SUPABASE CONNECTION TESTER")
    print("=" * 70)
    
    # Get current values
    current_host = os.getenv("POSTGRES_HOST", "").strip()
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    user = os.getenv("POSTGRES_USER", "").strip()
    password = os.getenv("POSTGRES_PASSWORD", "").strip()
    database = os.getenv("POSTGRES_DB", "").strip()
    
    print(f"\nCurrent configuration:")
    print(f"  Host: {current_host}")
    print(f"  Port: {port}")
    print(f"  User: {user}")
    print(f"  Database: {database}")
    
    if not all([current_host, user, password, database]):
        print("\n❌ Missing required environment variables!")
        return
    
    # Test 1: Try current hostname
    print(f"\n" + "=" * 70)
    print("TEST 1: Current hostname (Direct Connection)")
    print("=" * 70)
    success = await test_connection(current_host, port, user, password, database)
    
    if success:
        print("\n✅ Your current configuration works!")
        return
    
    # Test 2: Try connection pooler for each region
    print(f"\n" + "=" * 70)
    print("TEST 2: Connection Pooler (Port 6543)")
    print("=" * 70)
    
    # Extract project ref from current host if possible
    project_ref = None
    if "." in current_host:
        parts = current_host.split(".")
        if len(parts) >= 2:
            project_ref = parts[1] if parts[0] == "db" else parts[0]
    
    if not project_ref:
        print("⚠️  Cannot extract project reference from current host")
        print("Please go to Supabase Dashboard to get your connection string")
        return
    
    print(f"Extracted project ref: {project_ref}")
    print(f"Trying connection pooler with user: postgres.{project_ref}")
    
    for region in SUPABASE_REGIONS:
        pooler_host = f"aws-0-{region}.pooler.supabase.com"
        pooler_user = f"postgres.{project_ref}"
        print(f"\n{region}:")
        
        success = await test_connection(pooler_host, 6543, pooler_user, password, database)
        
        if success:
            print("\n" + "=" * 70)
            print("✅ FOUND WORKING CONNECTION!")
            print("=" * 70)
            print("\nUpdate your .env file with:")
            print(f'POSTGRES_HOST={pooler_host}')
            print(f'POSTGRES_PORT=6543')
            print(f'POSTGRES_USER=postgres.{project_ref}')
            print(f'POSTGRES_PASSWORD={password}')
            print(f'POSTGRES_DB={database}')
            print(f'\nDATABASE_URL=postgresql://postgres.{project_ref}:{password}@{pooler_host}:6543/{database}')
            print("\nThen update the same in your deployment platform!")
            return
    
    print("\n" + "=" * 70)
    print("❌ NO WORKING CONNECTION FOUND")
    print("=" * 70)
    print("\nPlease:")
    print("1. Go to https://supabase.com/dashboard")
    print("2. Select your project")
    print("3. Go to Settings → Database")
    print("4. Copy the connection string")
    print("5. Update your .env file")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest cancelled by user")
