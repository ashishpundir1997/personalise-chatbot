from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn
from app.chat.api.route import chat_router
from app.chat.service.session_service import ConversationManager
from app.chat.repository.chat_repository import ChatRepository
from app.core.logger import get_logger
from pkg.db_util.postgres_conn import PostgresConnection
from pkg.db_util.types import PostgresConfig
from app.auth.api.routes import auth_router
from app.user.api.routes import user_router
from pkg.redis.client import RedisClient
from pkg.redis.upstash_client import UpstashRedisClient
from pkg.smtp_client.client import EmailClient, EmailConfig
from pkg.auth_token_client.client import TokenClient
from app.user.repository.user_repository import UserRepository
from app.user.service.user_service import UserService
from app.auth.service.auth_service import AuthService
from app.agents.zep_user_service import ZepUserService
from dotenv import load_dotenv
import asyncio
import os
import sys
import socket

# App & Logger Setup
# Load .env so os.getenv picks up values from your .env file
load_dotenv()

logger = get_logger("neo-chat-wrapper")


async def check_database_connectivity(host: str, port: int, timeout: float = 10.0) -> dict:
    """Check if database host is reachable - non-blocking diagnostic only."""
    result = {
        "dns_resolved": False,
        "network_reachable": False,
        "ip_address": None,
        "error": None
    }
    
    try:
        # Try direct TCP connection (let asyncpg handle DNS internally)
        logger.info(f"Testing network connectivity to {host}:{port}...")
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            result["network_reachable"] = True
            result["dns_resolved"] = True
            logger.info(f"✓ Network connection successful to {host}:{port}")
        except Exception as e:
            result["error"] = f"Connection test failed: {e}"
            logger.warning(f"⚠️  Connection pre-check failed to {host}:{port}: {e}")
            logger.warning(f"⚠️  This may be normal - PostgreSQL will attempt connection anyway")
            
    except Exception as e:
        result["error"] = f"Unexpected error: {e}"
        logger.warning(f"⚠️  Connectivity check error: {e}")
    
    return result

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager - ensures startup completes before accepting requests"""
    # Startup
    logger.info("Neo Chat Wrapper starting up...")
    logger.info(f"Python: {sys.version}")
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"PORT from env: {os.getenv('PORT', 'NOT SET')}")
    
    # Debug: Print all environment variables (mask sensitive values)
    logger.info("=== Environment Variables Check ===")
    env_vars_to_check = ["POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", 
                         "POSTGRES_PORT", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"]
    for var in env_vars_to_check:
        value = os.getenv(var)
        if value:
            if "PASSWORD" in var or "TOKEN" in var or "SECRET" in var:
                logger.info(f"{var}: ***MASKED*** (length: {len(value)})")
            else:
                logger.info(f"{var}: {value}")
        else:
            logger.warning(f"{var}: NOT SET or EMPTY")
    logger.info("===================================")
    
    # Validate critical environment variables (strip whitespace)
    required_env_vars = {
        "POSTGRES_HOST": os.getenv("POSTGRES_HOST", "").strip(),
        "POSTGRES_USER": os.getenv("POSTGRES_USER", "").strip(),
        "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD", "").strip(),
        "POSTGRES_DB": os.getenv("POSTGRES_DB", "").strip(),
    }
    
    missing_vars = [key for key, value in required_env_vars.items() if not value]
    if missing_vars:
        error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
        logger.error(error_msg)
        logger.error("Please set these environment variables in your deployment platform")
        logger.error("Application will start in degraded mode")
        
        # Set minimal state so health endpoint works
        app.state.logger = logger
        app.state.postgres_conn = None
        app.state.redis_client = None
        app.state.startup_complete = False
        app.state.startup_error = error_msg
        
        yield  # App runs in degraded mode
        return
    
    logger.info(f"Connecting to database at: {required_env_vars['POSTGRES_HOST']}")
    
    # Check database connectivity before attempting connection (diagnostic only)
    db_host = required_env_vars["POSTGRES_HOST"]
    db_port = int(os.getenv("POSTGRES_PORT", "5432"))
    
    logger.info("Running connectivity pre-check (diagnostic only)...")
    connectivity = await check_database_connectivity(db_host, db_port, timeout=10.0)
    
    if not connectivity["network_reachable"]:
        logger.warning(f"⚠️  Connectivity pre-check failed: {connectivity['error']}")
        logger.warning("⚠️  This may be normal - PostgreSQL driver will attempt connection anyway")
        logger.warning("⚠️  The driver may have better network access than our pre-check")
    else:
        logger.info("✓ Connectivity pre-check passed")
    
    try:
        # Initialize Postgres connection with validated environment variables
        postgres_config = PostgresConfig(
            host=required_env_vars["POSTGRES_HOST"],
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            username=required_env_vars["POSTGRES_USER"],
            password=required_env_vars["POSTGRES_PASSWORD"],
            database=required_env_vars["POSTGRES_DB"],
            pool_timeout=30,  # Increase timeout for cloud deployments
        )
        postgres_conn = PostgresConnection(postgres_config, logger)
        chat_repo = ChatRepository(postgres_conn)
        
        # Initialize Postgres engine with timeout protection and retry logic
        logger.info("Initializing database engine with retry logic...")
        try:
            engine = await asyncio.wait_for(
                postgres_conn.get_engine(max_retries=5, initial_delay=2.0),
                timeout=60.0  # 60 second timeout for initial connection with retries
            )
            logger.info("✓ Postgres engine initialized and cached during startup.")
        except asyncio.TimeoutError:
            logger.error("Database connection timed out after 60 seconds")
            raise ConnectionError("Database connection timeout - check network/credentials")
        
        # Create all tables automatically if not present
        from pkg.db_util.sql_alchemy.declarative_base import Base
        # Import all models so SQLAlchemy registers them
        from app.chat.repository.sql_schema.conversation import ConversationModel, MessageModel
        from app.user.repository.sql_schema.user import UserModel
        
        logger.info("Skipping automatic table creation (use migrations or create manually)")
        logger.info("Tables needed: users, conversations, messages")
        # Note: Automatic table creation disabled due to Supabase connection pooler 
        # incompatibility with prepared statements.  Tables should already exist in production.
        # For development, run migrations manually or use direct connection (port 5432)
        
        # Wire auth-related services
        jwt_secret = os.getenv("JWT_SUPER_SECRET", "dev-secret")
        jwt_refresh_secret = os.getenv("JWT_REFRESH_SECRET", "dev-refresh-secret")
        token_client = TokenClient(jwt_secret, jwt_refresh_secret)
        
        # Redis client - Check if we should use Upstash REST API
        upstash_url = os.getenv("UPSTASH_REDIS_REST_URL")
        upstash_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
        
        if upstash_url and upstash_token:
            logger.info("Using Upstash Redis REST API...")
            redis_client = UpstashRedisClient(logger, url=upstash_url, token=upstash_token)
            # Test connection
            if redis_client.ping():
                logger.info("Connected to Upstash Redis successfully via REST API!")
            else:
                raise Exception("Failed to ping Upstash Redis")
        else:
            # Fallback to traditional Redis
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            redis_password = os.getenv("REDIS_PASSWORD") or None
            redis_ssl = os.getenv("REDIS_SSL", "false").lower() == "true"
            logger.info(f"Using traditional Redis at {redis_host}:{redis_port}")
            redis_client = RedisClient(logger, host=redis_host, port=redis_port, password=redis_password, ssl=redis_ssl)
            logger.info("Connected to Redis successfully!")
        
        # Initialize session_service
        session_service = ConversationManager(redis_client=redis_client, postgres_conn=postgres_conn)
        
        # Email client
        smtp_username = os.getenv("SMTP_USER_NAME", "")
        smtp_password = os.getenv("SMTP_PASSWORD", "")
        if smtp_username and smtp_password:
            email_cfg = EmailConfig( 
                smtp_server=os.getenv("SMTP_SERVER", "smtp.gmail.com"),
                smtp_port=int(os.getenv("SMTP_PORT", "587")),
                username=smtp_username,
                password=smtp_password,
                use_tls=os.getenv("SMTP_USE_TLS", "true").lower() != "false",
                max_retries=int(os.getenv("SMTP_MAX_RETRIES", "3")),
            )
            email_client = EmailClient(email_cfg)
        else:
            class _NoopEmailClient:
                async def send_email(self, *args, **kwargs):
                    logger.info("SMTP credentials not set; skipping email send (noop)")
                    return None
            email_client = _NoopEmailClient()
        
        # User repo/service
        user_repo = UserRepository(postgres_conn.get_session, logger)
        user_service = UserService(user_repo, logger, token_client)
        
        # Zep user service
        zep_user_service = None
        zep_api_key = os.getenv("ZEP_API_KEY")
        if zep_api_key:
            try:
                logger.info("Initializing Zep user service...")
                zep_user_service = ZepUserService(logger)
                logger.info("Zep user service initialized successfully")
                
                # Preload context template at startup
                try:
                    await asyncio.wait_for(
                        zep_user_service.ensure_context_template(max_retries=1, initial_delay=0.5, force_update=True),
                        timeout=10.0  # Max 10 seconds for Zep template
                    )
                    logger.info("Zep context template preloaded during startup")
                except asyncio.TimeoutError:
                    logger.warning("Zep context template preload timed out. Will retry on first use.")
                except Exception as e:
                    logger.warning(f"Failed to preload Zep context template: {e}. Will retry on first use.")
            except Exception as e:
                logger.warning(f"Failed to initialize Zep user service: {e}. Auth will continue without Zep integration.")
                zep_user_service = None
        else:
            logger.info("ZEP_API_KEY not set, skipping Zep integration")
            
        # Auth service
        auth_service = AuthService(user_service, token_client, redis_client, logger, email_client, zep_user_service)
        
        # Expose on app.state for dependencies
        app.state.logger = logger
        app.state.postgres_conn = postgres_conn
        app.state.chat_repo = chat_repo
        app.state.token_client = token_client
        app.state.redis_client = redis_client
        app.state.email_client = email_client
        app.state.user_repository = user_repo
        app.state.user_service = user_service
        app.state.auth_service = auth_service
        app.state.session_service = session_service
        app.state.zep_user_service = zep_user_service
        app.state.startup_complete = True
        app.state.startup_error = None
        
        logger.info("✓ Startup complete - application is ready!")
        
    except Exception as e:
        logger.error(f"✗ Startup failed: {e}", exc_info=True)
        logger.error("Application will start in degraded mode - check logs above")
        
        # Set minimal app.state so health endpoint works
        app.state.logger = logger
        app.state.postgres_conn = None
        app.state.redis_client = None
        app.state.startup_complete = False
        app.state.startup_error = str(e)
    
    # Application is running
    yield
    
    # Shutdown (cleanup if needed)
    logger.info("Neo Chat Wrapper shutting down...")

app = FastAPI(
    title="Neo Chat Wrapper",
    description="Unified LLM & Chat Orchestration Service",
    version="1.0.0",
    lifespan=lifespan
)

# Startup Check Middleware - ensures no requests processed before startup completes
class StartupCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Allow health checks during startup
        if request.url.path in ["/health", "/", "/docs", "/openapi.json"]:
            return await call_next(request)
        
        # Check if startup is complete
        if not getattr(request.app.state, "startup_complete", False):
            return JSONResponse(
                status_code=503,
                content={
                    "status": False,
                    "message": "Service is starting up. Please retry in a few seconds."
                }
            )
        
        # Check for startup errors
        startup_error = getattr(request.app.state, "startup_error", None)
        if startup_error:
            return JSONResponse(
                status_code=503,
                content={
                    "status": False,
                    "message": f"Service initialization failed: {startup_error}"
                }
            )
        
        return await call_next(request)

# Add middleware in correct order
app.add_middleware(StartupCheckMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # adjust in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Convert HTTPException to standardized error format"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": False,
            "message": exc.detail
        },
        headers=exc.headers
    )

# Routers
app.include_router(chat_router)
app.include_router(auth_router)
app.include_router(user_router)

# Health Check Endpoint
@app.get("/health")
async def health():
    """Enhanced health check that shows service status"""
    
    # Check startup status first
    startup_complete = getattr(app.state, "startup_complete", False)
    startup_error = getattr(app.state, "startup_error", None)
    
    # Return 200 for platform health checks even during startup
    # Include startup status in the response body
    if not startup_complete:
        return JSONResponse(
            status_code=200,  # Return 200 for health checks during startup
            content={
                "status": "starting" if startup_error is None else "degraded",
                "service": "neo-chat-wrapper",
                "message": startup_error or "Application is still starting up...",
                "startup_complete": False
            }
        )
    
    all_healthy = True
    checks = {}
    
    # Check if postgres is connected
    try:
        if hasattr(app.state, "postgres_conn") and app.state.postgres_conn:
            checks["database"] = "✓ connected"
        else:
            checks["database"] = "✗ not_initialized"
            all_healthy = False
    except Exception as e:
        checks["database"] = f"✗ error: {str(e)}"
        all_healthy = False
    
    # Check if redis is connected
    try:
        if hasattr(app.state, "redis_client") and app.state.redis_client:
            checks["redis"] = "✓ connected"
        else:
            checks["redis"] = "✗ not_initialized"
            all_healthy = False
    except Exception as e:
        checks["redis"] = f"✗ error: {str(e)}"
        all_healthy = False
    
    # Check other services
    checks["session_service"] = "✓ ready" if hasattr(app.state, "session_service") and app.state.session_service else "✗ not_ready"
    checks["auth_service"] = "✓ ready" if hasattr(app.state, "auth_service") and app.state.auth_service else "✗ not_ready"
    checks["user_service"] = "✓ ready" if hasattr(app.state, "user_service") and app.state.user_service else "✗ not_ready"
    
    status = {
        "status": "ok" if all_healthy else "degraded",
        "service": "neo-chat-wrapper",
        "checks": checks,
        "startup_complete": True
    }
    
    return status

@app.get("/")
async def root():
    """Root endpoint - simple check that app is running"""
    return {
        "service": "neo-chat-wrapper",
        "version": "1.0.0",
        "status": "running",
        "health_check": "/health"
    }

if __name__ == "__main__":
    # Use PORT from environment (Render provides this), fallback to 8080 for local
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)