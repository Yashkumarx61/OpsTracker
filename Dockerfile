# ============================================================
# OpsTracker — Production Dockerfile
# Optimized Python 3.11-slim image with MySQL client support & Gunicorn
# ============================================================

FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system packages for MySQL client compilation and health check
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        pkg-config \
        build-essential \
        default-libmysqlclient-dev && \
    rm -rf /var/lib/apt/lists/*

# Layer caching for requirements
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose Flask port 5000
EXPOSE 5000

# Health check probe on /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Run with Gunicorn on 0.0.0.0:5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "app:app"]
