FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# system deps kept minimal; psycopg[binary] ships its own libpq
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY data ./data
COPY dashboard ./dashboard

EXPOSE 8000

# uvicorn serves the FastAPI app; lifespan handles init_db + POS + auto-ingest
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
