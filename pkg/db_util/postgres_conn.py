from typing import Dict, Optional, Any, List, Tuple, Union, AsyncGenerator
from contextlib import asynccontextmanager
import urllib.parse
import asyncio
from pkg.db_util.types import PostgresConfig
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine, async_sessionmaker
from sqlalchemy.engine.url import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import event
from pkg.log.logger import get_logger


# Module-level singleton: Store engines by database URL to ensure only one engine per database
_engine_cache: Dict[str, AsyncEngine] = {}
_sessionmaker_cache: Dict[str, async_sessionmaker] = {}

# Module-level singleton: Store PostgresConnection instances by database URL
_connection_instances: Dict[str, 'PostgresConnection'] = {}


# Assume PostgresConfig, Logger, Base are imported correctly from their respective packages

class PostgresConnection:

    @staticmethod
    def _generate_db_url_from_config(db_config: PostgresConfig) -> str:
        """Generate database URL from config (used for singleton key)."""
        db_name = db_config.database
        host = db_config.host
        port = db_config.port
        username = db_config.username
        password = db_config.password  # Handle optional password

        # URL encode the password if it exists
        encoded_password = urllib.parse.quote_plus(password) if password else ''

        # Ensure host is provided; fallback isn't handled here, config should be correct
        if not host:
            raise ValueError("Database host configuration is missing.")

        url = f"postgresql+asyncpg://{username}:{encoded_password}@{host}:{port}/{db_name}"
        return url

    def __new__(cls, db_config: PostgresConfig, logger):
        """Singleton pattern: Return existing instance if one exists for this database URL."""
        # Generate URL to use as cache key
        db_url = cls._generate_db_url_from_config(db_config)
        
        # Return existing instance if it exists
        if db_url in _connection_instances:
            existing = _connection_instances[db_url]
            existing.logger.debug(f"Reusing existing PostgresConnection instance for database: {db_url[:50]}...")
            return existing
        
        # Create new instance
        instance = super().__new__(cls)
        instance._db_url = db_url
        _connection_instances[db_url] = instance
        return instance
    
    def __init__(self, db_config: PostgresConfig, logger):
        # __init__ is called even for existing instances, so check if already initialized
        if hasattr(self, '_initialized'):
            return
        self.logger = logger
        self.db_config = db_config
        self._initialized = True

    def _generate_db_url(self) -> str:
        """Generate database URL (instance method)."""
        return self._generate_db_url_from_config(self.db_config)
    
    def get_db_url(self) -> str:
        """Get database URL (public method)."""
        if self._db_url is None:
            self._db_url = self._generate_db_url()
        return self._db_url

    async def get_engine(self, max_retries: int = 3, initial_delay: float = 2.0) -> AsyncEngine:
        """Get or create engine using module-level singleton pattern with retry logic."""
        if self._db_url is None:
            self._db_url = self.get_db_url()
        
        # Check if engine already exists in module-level cache (singleton)
        if self._db_url in _engine_cache:
            return _engine_cache[self._db_url]
        
        # Create new engine and store in module-level cache with retry logic
        self.logger.info("Database engine not initialized. Creating new engine...")
        pool_opts = {
            "pool_size": self.db_config.pool_size,
            "max_overflow": self.db_config.max_overflow,
            "pool_timeout": self.db_config.pool_timeout,
            "pool_recycle": self.db_config.pool_recycle,  # Recycle connections e.g., every 30 mins
            "pool_pre_ping": True,  # Enable connection health checks
        }
        self.logger.info(f"Creating async engine with pool options: {pool_opts}")
        
        last_error = None
        for attempt in range(max_retries):
            try:
                engine = create_async_engine(
                    self._db_url,
                    echo=False,  # Set to True for debugging SQL
                    # echo_pool="debug", # Set to "debug" for verbose pool logging
                    connect_args={
                        "timeout": 15,  # Connection timeout in seconds
                        "command_timeout": 15,  # Command timeout
                        "server_settings": {
                            "application_name": "neo-chat-wrapper"
                        }
                    },
                    **pool_opts
                )
                
                # Test the connection immediately
                self.logger.info(f"Testing database connection (attempt {attempt + 1}/{max_retries})...")
                async with engine.connect() as conn:
                    self.logger.info("Database connection tested successfully.")

                sessionmaker = async_sessionmaker(
                    bind=engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                )
                
                # Store in module-level cache (singleton pattern)
                _engine_cache[self._db_url] = engine
                _sessionmaker_cache[self._db_url] = sessionmaker
                self.logger.info("Async engine and sessionmaker created successfully and cached.")
                return engine

            except (SQLAlchemyError, OSError, ConnectionError) as e:
                last_error = e
                delay = initial_delay * (2 ** attempt)  # Exponential backoff
                
                if attempt < max_retries - 1:
                    self.logger.warning(
                        f"Database connection attempt {attempt + 1}/{max_retries} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    self.logger.error(f"Failed to create database engine after {max_retries} attempts: {e}", exc_info=True)
            except Exception as e:
                last_error = e
                self.logger.error(f"An unexpected error occurred during engine creation: {e}", exc_info=True)
                break
        
        # If we get here, all retries failed
        raise ConnectionError(f"Could not create database engine after {max_retries} attempts: {last_error}") from last_error

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provides an asynchronous SQLAlchemy session with better logging"""
        if self._db_url is None:
            self._db_url = self.get_db_url()
        
        # Ensure engine is initialized (will use singleton from cache if exists)
        await self.get_engine()
        
        # Get sessionmaker from module-level cache
        sessionmaker = _sessionmaker_cache.get(self._db_url)
        if sessionmaker is None:
            self.logger.error("Sessionmaker is not available even after engine initialization attempt.")
            raise ConnectionError("Database engine/sessionmaker not initialized.")

        session: AsyncSession = sessionmaker()
        session_id = id(session)
        # self.logger.debug(f"Acquired session {session_id}.")

        # Log current pool status - helpful for debugging connection issues
        # if self._engine and hasattr(self._engine.pool, "status"):
        #     self.logger.debug(f"Pool status: {self._engine.pool.status()}")

        try:
            yield session
        except SQLAlchemyError as e:
            self.logger.error(f"SQLAlchemy error in session {session_id}: {e}. Rolling back.", exc_info=True)
            await session.rollback()
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in session {session_id}: {e}. Rolling back.", exc_info=True)
            await session.rollback()
            raise
        finally:
            await session.close()
            # self.logger.debug(f"Closed session {session_id}.")

    async def close_engine(self):
        """Close engine and remove from module-level cache."""
        if self._db_url and self._db_url in _engine_cache:
            self.logger.info("Closing database engine and connection pool...")
            engine = _engine_cache[self._db_url]
            await engine.dispose()
            # Remove from cache
            del _engine_cache[self._db_url]
            if self._db_url in _sessionmaker_cache:
                del _sessionmaker_cache[self._db_url]
            self.logger.info("Database engine closed and removed from cache.")
        else:
            self.logger.info("Database engine was not initialized, no need to close.")


async def close_all_engines():
    """Close all engines in the module-level cache. Useful for application shutdown."""
    for db_url, engine in list(_engine_cache.items()):
        try:
            await engine.dispose()
            del _engine_cache[db_url]
            if db_url in _sessionmaker_cache:
                del _sessionmaker_cache[db_url]
        except Exception as e:
            # Log but don't fail on cleanup errors
            get_logger(__name__).error(f"Error closing engine for {db_url[:50]}...: {e}")