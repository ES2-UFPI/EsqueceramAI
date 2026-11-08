FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    UPLOAD_DIR=/app/storage

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY sql ./sql
COPY init_db.py .
COPY extensions.py models.py seed.py ./

RUN mkdir -p /app/storage

EXPOSE 10000

CMD ["sh", "-c", "python init_db.py && gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120 app:app"]
