FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=10000

COPY app.py .

# CORREÇÃO: Aponta para o caminho correto dentro do subdiretório backend
COPY backend/requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

# CORREÇÃO: Copia todo o conteúdo da pasta backend para o diretório de trabalho do contêiner
COPY backend/ .

EXPOSE 10000

# Garante que o gunicorn encontre o app.py que agora está na raiz do WORKDIR (/app)
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} app:app"]
