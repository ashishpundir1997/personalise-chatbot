from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
# App & Logger Setup
# Load .env so os.getenv picks up values from your .env file
load_dotenv()
app = FastAPI(
    title="Neo Chat Wrapper",
    description="Unified LLM & Chat Orchestration Service",
    version="1.0.0",
)
logger = get_logger("neo-chat-wrapper")
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
# DB & Services Initialization
postgres_config = PostgresConfig(
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=int(os.getenv("POSTGRES_PORT", "5432")),
    username=os.getenv("POSTGRES_USER", "postgres"),
    password=os.getenv("POSTGRES_PASSWORD", ""),
    database=os.getenv("POSTGRES_DB", "projectneo"),
)
postgres_conn = PostgresConnection(postgres_config, logger)
chat_repo = ChatRepository(postgres_conn)

# Routers
app.include_router(chat_router)
app.include_router(auth_router)
app.include_router(user_router)
@app.on_event("startup")
async def on_startup():
    logger.info("Neo Chat Wrapper starting up...")
    try:
        # Initialize Postgres engine ONCE during startup (stored in module-level singleton cache)
        engine = await postgres_conn.get_engine()
        logger.info("Postgres engine initialized and cached during startup.")
        # Create all tables automatically if not present
        from pkg.db_util.sql_alchemy.declarative_base import Base
        # Import all models so SQLAlchemy registers them
        from app.chat.repository.sql_schema.conversation import ConversationModel, MessageModel
        from app.user.repository.sql_schema.user import UserModel
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("All database tables ensured.")
        except Exception as e:
            logger.error(f"Error creating database tables: {e}", exc_info=True)
            raise
        # Wire auth-related services (replaces removed container)
        # Logger already created above
        # Token client from env
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
        
        # Initialize session_service (use shared postgres_conn to avoid creating new engine per request)
        session_service = ConversationManager(redis_client=redis_client, postgres_conn=postgres_conn)
        # Email client (use no-op in dev if creds missing)
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
        # Zep user service (for linking users to Zep)
        try:
            zep_user_service = ZepUserService(logger)
            logger.info("Zep user service initialized successfully")
            
            # Preload context template at startup (with retry logic for 503 errors)
            # This avoids repeated creation attempts during request handling
            # Force update to ensure template has latest content (no RECENT EPISODES)
            try:
                await zep_user_service.ensure_context_template(max_retries=2, initial_delay=0.5, force_update=True)
                logger.info("Zep context template preloaded during startup")
            except Exception as e:
                logger.warning(f"Failed to ensure Zep context template during startup: {e}. Will retry on first use.")
        except Exception as e:
            logger.warning(f"Failed to initialize Zep user service: {e}. Auth will continue without Zep integration.")
            zep_user_service = None
        # Auth service and handler
        auth_service = AuthService(user_service, token_client, redis_client, logger, email_client, zep_user_service)
        # Expose on app.state for dependencies
        app.state.logger = logger
        app.state.token_client = token_client
        app.state.redis_client = redis_client
        app.state.email_client = email_client
        app.state.user_repository = user_repo
        app.state.user_service = user_service
        app.state.auth_service = auth_service
        app.state.session_service = session_service
        app.state.zep_user_service = zep_user_service
        logger.info("Startup complete.")
    except Exception as e:
        logger.error(f"Startup failed: {e}", exc_info=True)
        raise e
    
    
# Health Check Endpoint
@app.get("/health")
async def health():
    return {"status": "ok", "service": "neo-chat-wrapper"}
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)