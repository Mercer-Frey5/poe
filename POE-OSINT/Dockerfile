FROM python:3.12-slim

# Metadati
LABEL org.opencontainers.image.title="POE — Personal Observation Engine"
LABEL org.opencontainers.image.version="0.1.0"
LABEL org.opencontainers.image.source="personal-project"

WORKDIR /app

# Dipendenze di sistema minime (spaCy non richiede C toolchain grazie ai wheel)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Layer Python — separato per sfruttare la cache quando solo il codice cambia
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modelli spaCy — layer separato, pesa ~1GB ma cambia raramente
RUN python -m spacy download it_core_news_lg \
    && python -m spacy download en_core_web_lg

# Codice applicativo
COPY app ./app
COPY static ./static

# Volume per il DB (montato da docker-compose)
RUN mkdir -p /app/data

EXPOSE 8000

# Healthcheck interno — corrisponde alla route /health di main.py
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
