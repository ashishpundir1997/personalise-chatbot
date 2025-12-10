#!/bin/bash
# Railway startup script with better logging

echo "=================================================="
echo "Starting Neo Chat Wrapper"
echo "=================================================="
echo "Python version: $(python --version)"
echo "Working directory: $(pwd)"
echo "PORT: ${PORT:-'not set'}"
echo "POSTGRES_HOST: ${POSTGRES_HOST:-'not set'}"
echo "=================================================="

# Start the application
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --timeout-keep-alive 120 --log-level info
