FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Init DB on startup via entrypoint wrapper
ENTRYPOINT ["sh", "-c", "python -c 'from src.database import init_db; init_db()' && uvicorn main:app --host 0.0.0.0 --port $PORT"]
