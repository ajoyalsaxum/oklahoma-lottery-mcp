FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer-cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY api.py cache.py constants.py http_server.py ./

EXPOSE 8000

# Render / Railway pass PORT as an env var; fall back to 8000 locally
CMD ["sh", "-c", "uvicorn http_server:app --host 0.0.0.0 --port ${PORT:-8000}"]
