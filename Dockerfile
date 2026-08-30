# =========================================
# Base: shared Python + dependencies layer
# =========================================
FROM python:3.11-slim AS base

WORKDIR /app

# System deps needed by psycopg2 and sentence-transformers' tokenizers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# =========================================
# Backend target: FastAPI
# =========================================
FROM base AS backend

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.api.routes:app", "--host", "0.0.0.0", "--port", "8000"]

# =========================================
# Frontend target: Streamlit
# =========================================
FROM base AS frontend

EXPOSE 8501

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "frontend/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]
