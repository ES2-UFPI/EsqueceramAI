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

### Conexão com o banco em produção

O `DATABASE_URL` aponta para o banco do projeto Supabase e usa a **senha do banco**
(Project Settings → Database), não as chaves de API `sb_*`. Se a senha tiver caracteres
especiais, percent-encode-os.

Use o **pooler** como host, na porta padrão `5432` (session pooler). O endereço direto
`db.<ref>.supabase.co` só publica registro IPv6, portanto não funciona em serviços que não
roteiam IPv6 — o caso do Render:

```dotenv
# direto (somente IPv6 — não funciona no Render)
DATABASE_URL=postgresql://postgres:SENHA@db.gmgxcsztfpoxdbstrvwx.supabase.co:5432/postgres

# pooler (IPv4 — use este em produção, porta padrão 5432)
DATABASE_URL=postgresql://postgres.gmgxcsztfpoxdbstrvwx:SENHA@aws-0-us-west-1.pooler.supabase.com:5432/postgres
```

Note que no pooler o usuário recebe o sufixo `.<project-ref>`. A porta `6543` é a do
transaction pooler, que não é a padrão e não é necessária aqui.

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

## 4. URL da API no frontend

O `frontend/app.js` escolhe o destino das requisições pelo host que serve a página:

| Ambiente | URL usada |
|:---|:---|
| GitHub Pages (`*.github.io`) | `https://esqueceramai.onrender.com/api` |
| Local via Nginx do Compose (`localhost:8080`) | `/api` — o Nginx encaminha para o serviço `api` |
| Arquivo aberto direto (`file://`) | `http://localhost:5000/api` |

Assim o ambiente local grava e lê no PostgreSQL do Compose, sem depender da API publicada.
A URL pública do Render fica restrita ao GitHub Pages. Para apontar para outro backend,
defina `window.ESQUECERAM_API` antes de carregar o `app.js`.

## 5. Resumo das alterações

| Arquivo | Alteração |
|:---|:---|
| `backend/.env` | Novas variáveis do Supabase (arquivo local, não versionado) |
| `backend/.env.example` | Modelo atualizado com as chaves `sb_publishable_`/`sb_secret_` e a JWKS |
| `supabase/config.toml` | Configuração do projeto para o Supabase CLI |
| `supabase/migrations/20261106000000_initial_schema.sql` | Schema inicial consolidado |
| `backend/init_db.py` | Passa a aplicar as migrations de `supabase/migrations/` |
| `docker-compose.yaml` | Monta a migration no `docker-entrypoint-initdb.d` |
| `backend/Dockerfile` | Deixa de copiar a pasta `sql`, removida |
| `frontend/app.js` | Usa a API local fora do GitHub Pages; Render só em produção |
| `backend/sql/schema.sql` | Removido (substituído pela migration) |
