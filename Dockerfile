# 2026 SOTA Mothership Image (Highly Optimized)
FROM python:3.11-slim

# Avoid writing .pyc files & enable stdout logging for Fly.io metrics
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (caching layer optimization)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Expose the internal port expected by fly.toml
EXPOSE 8000

# Start UvicornASGI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
