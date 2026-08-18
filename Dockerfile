# Multi-architecture Dockerfile for Personal AI Outreach System
# Supports linux/amd64 and linux/arm64 (Oracle Cloud Ampere A1)
FROM python:3.12-slim

# Prevent Python from writing .pyc and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY . .

# Ensure data and backup directories exist
RUN mkdir -p /app/data /app/data/backups /app/profile

# Expose port for healthcheck and manual trigger API
EXPOSE 8000

# Run FastAPI app with Telegram polling and scheduler
CMD ["python", "app.py"]
