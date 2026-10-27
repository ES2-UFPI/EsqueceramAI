FROM python:3.12-slim

# CORREÇÃO: Utiliza caminho absoluto para evitar o warning e bugs de contexto
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=10000

# Cache de dependências: copia apenas o arquivo de pacotes primeiro
COPY requirements.txt .

# Atualiza o pip e instala as dependências sem salvar lixo no cache do contêiner
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

# Copia o restante do código fonte do projeto para o WORKDIR (/app)
COPY . .

EXPOSE 10000

# Executa o gunicorn apontando para o app de forma direta e limpa
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} app:app"]
