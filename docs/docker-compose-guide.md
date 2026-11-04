# Guia do ambiente local (Docker Compose)

O `docker-compose.yaml` na raiz do projeto sobe a API, o PostgreSQL e o frontend em uma
rede única, com dados persistidos em volumes.

## Serviços

| Serviço | Imagem / build | Porta | Descrição |
|:---|:---|:---|:---|
| `api` | `./backend/Dockerfile` | 5000 → 10000 | Flask servido por Gunicorn |
| `db` | `postgres:16-alpine` | 5432 (interna) | PostgreSQL com o schema aplicado na primeira execução |
| `frontend` | `./frontend/Dockerfile` | 8080 → 80 | Nginx servindo os arquivos estáticos e proxiando `/api` |

## Comandos

Iniciar (construindo as imagens):

```bash
docker compose up --build
```

Encerrar:

```bash
docker compose down
```

Encerrar e apagar os dados (banco e imagens enviadas):

```bash
docker compose down -v
```

Ver o estado dos serviços, incluindo os healthchecks:

```bash
docker compose ps
```

Ver os logs de um serviço:

```bash
docker compose logs -f api
```

## Acesso

- Frontend: <http://localhost:8080>
- API: <http://localhost:5000>
- Healthcheck da API: <http://localhost:5000/api/health>

## Ordem de inicialização

O `db` possui um healthcheck com `pg_isready`, e a `api` só inicia quando ele passa
(`depends_on: condition: service_healthy`). O schema em `backend/sql/schema.sql` é montado
em `/docker-entrypoint-initdb.d`, sendo aplicado automaticamente na primeira subida com o
volume vazio.

## Persistência

| Volume | Conteúdo |
|:---|:---|
| `postgres_data` | Dados do PostgreSQL |
| `uploads` | Imagens dos itens enviadas para a API |

Os volumes sobrevivem a `docker compose down`. Para recriar o banco do zero, use
`docker compose down -v`.

## Variáveis de ambiente

| Variável | Serviço | Valor padrão no Compose |
|:---|:---|:---|
| `DATABASE_URL` | api | `postgresql://esqueceram_ai:esqueceram_ai@db:5432/esqueceram_ai` |
| `FRONTEND_ORIGIN` | api | `http://localhost:8080` |
| `PORT` | api | `10000` |
| `UPLOAD_DIR` | api | `/app/storage` |
