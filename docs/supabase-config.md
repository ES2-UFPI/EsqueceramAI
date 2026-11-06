# Configuração do Supabase

O projeto passou a usar o **Supabase** como provedor de banco de dados, autenticação e
armazenamento de imagens. Este documento registra as variáveis de ambiente necessárias e
como aplicar o schema — no Supabase e no ambiente local.

## 1. Variáveis de ambiente

As variáveis ficam no arquivo `backend/.env`, que **não é versionado** (consta no
`.gitignore`). Use `backend/.env.example` como modelo.

| Variável | Descrição |
|:---|:---|
| `SUPABASE_URL` | URL do projeto Supabase (`https://<ref>.supabase.co`) |
| `SUPABASE_PUBLISHABLE_KEY` | Chave publicável (`sb_publishable_...`). Pode ir para o frontend; respeita as políticas de acesso. |
| `SUPABASE_SECRET_KEY` | Chave secreta (`sb_secret_...`). **Somente no backend** — ignora o RLS. Nunca exponha em código de cliente. |
| `SUPABASE_JWKS_URL` | Endpoint JWKS do GoTrue, usado para validar os JWT emitidos pelo Supabase Auth. |
| `SUPABASE_STORAGE_BUCKET` | Nome do bucket de imagens (`item-images`). |
| `DATABASE_URL` | Connection string do PostgreSQL. Local por padrão; troque pelo do painel do Supabase para usar o banco remoto. |

```dotenv
SUPABASE_URL=https://gmgxcsztfpoxdbstrvwx.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
SUPABASE_SECRET_KEY=sb_secret_...
SUPABASE_JWKS_URL=https://gmgxcsztfpoxdbstrvwx.supabase.co/auth/v1/.well-known/jwks.json
```

> Em produção (Render), cadastre as mesmas chaves em **Environment → Environment Variables**
> do serviço. Não versione o `.env`.

## 2. Migrations

O schema agora vive em `supabase/migrations/` e é a **única fonte de verdade**:

```
supabase/
├── config.toml
└── migrations/
    └── 20261106000000_initial_schema.sql
```

A migration inicial consolida o schema que antes ficava em `backend/sql/schema.sql`
(enums, tabelas, índices, triggers, view `pontuacao_usuario` e a função `reservar_item`).
Nenhuma decisão de modelagem mudou — apenas o formato passou a ser o de migration, para
poder ser aplicado tanto no Supabase quanto localmente.

### Aplicar no Supabase

Com o [Supabase CLI](https://supabase.com/docs/guides/cli) instalado e autenticado:

```bash
supabase link --project-ref gmgxcsztfpoxdbstrvwx
supabase db push
```

### Aplicar em um banco novo

Crie uma migration a partir de qualquer alteração de schema, em vez de editar a existente:

```bash
supabase migration new <nome_da_alteracao>
```

## 3. Execução local

O mesmo arquivo de migration é usado no ambiente local, então o schema nunca diverge.

### Com Docker Compose

```bash
docker compose up --build
```

O PostgreSQL aplica a migration automaticamente na primeira subida, quando o volume
`postgres_data` está vazio, via `/docker-entrypoint-initdb.d`.

### Sem Docker (Python)

```bash
cd backend
python init_db.py            # cria o banco e aplica as migrations
python init_db.py --seed     # além disso, insere dados de exemplo
python init_db.py --reset    # recria do zero (apenas banco LOCAL)
```

O `init_db.py` procura por `supabase/migrations/*.sql` e aplica os arquivos em ordem
alfabética, o que coincide com a ordem cronológica usada pelo Supabase.

Para recriar o banco do Compose do zero: `docker compose down -v` e suba novamente.

## 4. Resumo das alterações

| Arquivo | Alteração |
|:---|:---|
| `backend/.env` | Novas variáveis do Supabase (arquivo local, não versionado) |
| `backend/.env.example` | Modelo atualizado com as chaves `sb_publishable_`/`sb_secret_` e a JWKS |
| `supabase/config.toml` | Configuração do projeto para o Supabase CLI |
| `supabase/migrations/20261106000000_initial_schema.sql` | Schema inicial consolidado |
| `backend/init_db.py` | Passa a aplicar as migrations de `supabase/migrations/` |
| `docker-compose.yaml` | Monta a migration no `docker-entrypoint-initdb.d` |
| `backend/sql/schema.sql` | Removido (substituído pela migration) |
