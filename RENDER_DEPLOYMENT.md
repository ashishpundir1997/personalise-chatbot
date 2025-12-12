# Render Deployment Guide

## Prerequisites

1. **Render Account** - Sign up at https://render.com
2. **GitHub Repository** - Push your code to GitHub
3. **Database** - Use Render Postgres or external (Supabase)

## Quick Deploy to Render

### 1. Create Web Service

1. Go to Render Dashboard → **New** → **Web Service**
2. Connect your GitHub repository: `ashishpundir1997/personalise-chatbot`
3. Configure:
   - **Name**: `neo-chat-wrapper` (or your choice)
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free or Starter

### 2. Set Environment Variables

In Render Dashboard → Your Service → **Environment**, add:

```bash
# Required
POSTGRES_HOST=<your-db-host>
POSTGRES_PORT=5432
POSTGRES_USER=<your-db-user>
POSTGRES_PASSWORD=<your-db-password>
POSTGRES_DB=<your-db-name>
DATABASE_URL=postgresql://<user>:<password>@<host>:<port>/<database>

# Redis (Upstash)
UPSTASH_REDIS_REST_URL=https://prompt-alien-5300.upstash.io
UPSTASH_REDIS_REST_TOKEN=<your-token>

# JWT
JWT_SUPER_SECRET=<generate-random-secret>
JWT_REFRESH_SECRET=<generate-random-secret>

# SMTP (AWS SES)
SMTP_SERVER=email-smtp.eu-north-1.amazonaws.com
SMTP_PORT=587
SMTP_USER_NAME=<your-smtp-user>
SMTP_PASSWORD=<your-smtp-password>

# Google OAuth
GOOGLE_OAUTH_CLIENT_ID=<your-client-id>
GOOGLE_OAUTH_CLIENT_SECRET=<your-client-secret>

# LLM Providers
GEMINI_API_KEY=<your-gemini-key>
GEMINI_MODEL=gemini-1.5-flash
ENABLED_PROVIDERS=gemini

# Zep (optional)
ZEP_API_KEY=<your-zep-key>
```

### 3. Database Setup

#### Option A: Use Render Postgres

1. Create Render Postgres: Dashboard → **New** → **PostgreSQL**
2. Copy connection details to environment variables
3. Run table creation:
   ```bash
   # Locally with Render's DATABASE_URL
   export DATABASE_URL="<render-postgres-url>"
   python scripts/create_tables_sync.py
   ```

#### Option B: Use External Database (Supabase)

1. Use your existing Supabase database
2. Set environment variables to point to Supabase
3. Tables should already exist from earlier setup

### 4. Deploy

1. Click **Deploy** in Render Dashboard
2. Monitor logs for startup
3. Check health: `https://your-app.onrender.com/health`

## Database Table Creation

If tables don't exist, run locally:

```bash
# Get DATABASE_URL from Render environment variables
export DATABASE_URL="<your-database-url>"

# Run table creation script
python scripts/create_tables_sync.py
```

Or manually via SQL console (use `postgres_schema.sql`).

## Health Check

Render uses: `GET /health`

Response format:
```json
{
  "status": "ok",
  "service": "neo-chat-wrapper",
  "checks": {
    "database": "✓ connected",
    "redis": "✓ connected",
    "session_service": "✓ ready",
    "auth_service": "✓ ready",
    "user_service": "✓ ready"
  },
  "startup_complete": true
}
```

## Important Notes

- **Port**: Render provides `$PORT` automatically (don't hardcode)
- **Start Command**: Uses Procfile or manual uvicorn command
- **Cold Starts**: Free tier sleeps after inactivity (first request takes ~30s)
- **Logs**: Available in Render Dashboard → Logs tab
- **Auto-Deploy**: Enabled by default on git push

## Troubleshooting

### Database Connection Issues
- Verify `DATABASE_URL` format: `postgresql://user:pass@host:port/db`
- Check firewall rules if using external DB
- Enable connection pooling for better performance

### Startup Timeout
- Render has 60s startup timeout
- Check logs for slow operations
- Optimize imports and startup code

### 503 Errors
- Check `/health` endpoint
- Verify all environment variables are set
- Review application logs

## Useful Commands

```bash
# Test locally with Render env vars
render env pull
uvicorn main:app --reload

# View logs
render logs -f

# Open service URL
render open
```

## Next Steps

1. Set up custom domain (if needed)
2. Configure auto-scaling
3. Set up monitoring/alerts
4. Enable HTTPS (automatic on Render)
5. Add CI/CD via GitHub Actions
