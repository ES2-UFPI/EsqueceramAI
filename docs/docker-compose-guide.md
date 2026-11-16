# Guia do ambiente local (Docker Compose)

O `docker-compose.yaml` na raiz do projeto sobe a aplicação Flask (`api`) e o PostgreSQL (`db`) em uma rede única, com os dados do banco persistidos em volume.

## Serviços

| Serviço | Imagem / build | Porta | Descrição |
|:---|:---|:---|:---|
| `api` | `./Dockerfile` | `10000:10000` | Aplicação web e API Flask servida por Gunicorn |
| `db` | `postgres:16-alpine` | `5432` (interna) | PostgreSQL com o schema aplicado na primeira execução |

## Comandos

Iniciar (construindo a imagem):

```bash
docker compose up --build
```

Encerrar:

```bash
docker compose down
```

Encerrar e apagar os dados do banco:

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

- Aplicação web e API: <http://localhost:10000>
- Healthcheck da API: <http://localhost:10000/api/health>

## Ordem de inicialização

O `db` possui um healthcheck com `pg_isready`, e a `api` só inicia quando ele passa (`depends_on: condition: service_healthy`). A migration inicial em `supabase/migrations/20261106000000_initial_schema.sql` — a mesma aplicada no Supabase — é montada em `/docker-entrypoint-initdb.d`, sendo aplicada automaticamente na primeira subida com o volume vazio. Na inicialização da aplicação, `init_db()` também sincroniza colunas ausentes e valores do enum `item_status`.

## Persistência

| Volume | Conteúdo |
|:---|:---|
| `postgres_data` | Dados do PostgreSQL |

O volume sobrevive a `docker compose down`. Para recriar o banco do zero, use `docker compose down -v`.

## Variáveis de ambiente

| Variável | Serviço | Valor padrão no Compose |
|:---|:---|:---|
| `DATABASE_URL` | `api` | `postgresql://esqueceram_ai:esqueceram_ai@db:5432/esqueceram_ai` |
| `PORT` | `api` | `10000` |
