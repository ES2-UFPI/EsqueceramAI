# Guia de Composição de Containers Docker

Pasta destinada aos documentos técnicos, decisões de arquitetura, guias de uso e demais registros do projeto.

## Procedimento de Inicialização

Para iniciar todos os serviços localmente com o banco PostgreSQL saudável antes de o backend começar:

```powershell
# Na pasta do projeto (raiz), executando no terminal do Windows
docker compose up --build
```

**Comportamento esperado:**
1. O serviço `db` (PostgreSQL) é iniciado e aguarda 30 segundos para saudável.
2. O serviço `backend` (Flask/Gunicorn) é iniciado apenas após a DB estar saudável (`depends_on: condition: service_healthy`).
3. O serviço `frontend` (Nginx) é iniciado após o backend, pois depende dele.

## Procedimento de Encerramento

Para encerrar todos os serviços e limpar os containers:

```powershell
# Para encerrar apenas os containers (mantém as imagens na cache)
docker compose down

# Para remover os containers, volumes e rede (cuidado: apaga todos os dados do PostgreSQL)
docker compose down -v
```

## Saídas dos Serviços

| Serviço       | Endereço Local         | Descrição                              |
| ------------- | ---------------------- | -------------------------------------- |
| `backend`     | http://localhost:5000 | API Flask exposta na porta 5000       |
| `frontend`    | http://localhost:8080 | Nginx servindo o frontend estático     |
| `db`          | localhost:5432        | Banco de dados PostgreSQL             |
| `/api/health` | http://localhost:5000 | Endpoint de saúde do backend          |
| `/api/itens`  | http://localhost:5000 | Endpoint de itens (exemplo)           |
| `/api/usuarios` | http://localhost:5000| Endpoint de usuários (exemplo)        |

## Varreduras de Saúde

- **Backend:** GET /api/health retorna `{"status": "healthy", "scope": "global_api"}`
- **PostgreSQL:** Utiliza o healthcheck configurado com `pg_isready -U postgres`

## Variáveis de Ambiente Defasadas

As variáveis de ambiente padrão definidas no `docker-compose.yaml` são:

| Variável        | Valor                  | Origem                       |
| --------------- | ---------------------- | ---------------------------- |
| PORT            | 10000                  | Backend Gunicorn            |
| DATABASE_URL    | postgresql://...      | Compose                     |
| PYTHONUNBUFFERED | 1                      | Backend                     |

As variáveis de produção (Render, Supabase, etc.) devem ser configuradas separadamente, nunca versionadas no repositório.