FROM node:20-alpine AS js-obfuscator
WORKDIR /build
COPY application/web/static/app.js ./app.js
RUN npx --yes javascript-obfuscator ./app.js --output ./app.obfuscated.js --compact true --self-defending false

FROM python:3.12-slim

WORKDIR /service
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=10000

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

COPY . ./
COPY --from=js-obfuscator /build/app.obfuscated.js ./application/web/static/app.js

EXPOSE 10000
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 2 --threads 4 --timeout 120 app:app"]
