# Esqueceram AI — Achados e perdidos da comunidade acadêmica (Python / Flask)

Versão em **Python** do projeto (antes Next.js + Drizzle). Preserva o **domínio**, o **contrato REST**, o
**pt-BR** e a **arquitetura em camadas** `Controller → Service → Repository → PostgreSQL/Storage`.

## Como executar

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # opcional
python run.py                                          # http://localhost:3000
```

- Com `DATABASE_URL=postgresql://...` usa PostgreSQL (as tabelas são criadas na inicialização,
  equivalente ao `drizzle-kit push`). **Sem** `DATABASE_URL`, usa SQLite local (`esqueceram.db`).
- Produção: `gunicorn -w 2 -b 0.0.0.0:3000 run:app` (após `pip install gunicorn`).
- O primeiro acesso a `/`, `/itens`, ao login ou a `/api/health` popula o dataset demonstrativo (idempotente).

## Mapa TypeScript → Python

| Original (TS) | Python |
| --- | --- |
| `src/db/schema.ts` (Drizzle) | `app/models.py` (SQLAlchemy 2) |
| `src/lib/domain.ts` | `app/domain.py` |
| `src/server/auth.ts` | `app/auth.py` (scrypt compatível com o original) |
| `src/server/http.ts`, `errors.ts`, Zod | `app/http.py`, `app/errors.py`, `app/validation.py` |
| `src/server/repositories/*` | `app/repositories/*` |
| `src/server/services/*` | `app/services/*` (auth, item, matching, storage, stats, seed) |
| `src/app/api/**/route.ts` | `app/api/routes.py` |
| `src/app/**/page.tsx` + componentes | `app/web/views.py` + `app/web/templates/*.html` (Jinja) |

## API REST (CORS habilitado, idêntica à original)

Cookie `esqueceram_session` ou `Authorization: Bearer <token>`. Filtros em português: `q, tipo, categoria,
status, local, cor, marca, modelo, de, ate, ordem, pagina`.

| Método | Endpoint |
| --- | --- |
| POST | `/api/auth/register` · `/login` · `/demo` · `/recover` · `/logout` |
| GET/PATCH | `/api/auth/me` · PATCH `/api/auth/password` |
| GET/POST | `/api/items` (POST = `multipart/form-data`, campo `image`) |
| GET/PATCH/DELETE | `/api/items/:id` (PATCH: multipart edita; JSON `{status}` altera status) |
| GET | `/api/images/:id` (privado, exige sessão) |
| GET/PATCH | `/api/matches` · `/api/matches/:id` (`confirm` / `reject`) |
| GET/PATCH | `/api/notifications` |
| GET/POST/PATCH | `/api/points` |
| GET/PATCH | `/api/admin/users` (ADMIN) |
| GET | `/api/health` |

## Contas de demonstração (senha `esqueceram123`)

`ana@`, `carlos@`, `operador@`, `admin@ufpi.edu.br` — a tela de login tem acesso rápido de 1 clique.
Desative em produção com `DEMO_LOGIN_DISABLED=true`.

## Entrega com respaldo legal (checkout no posto)

Atendente do posto registra a retirada com **CPF validado**, **foto do documento**, **código de confirmação
por e-mail** e emite o **termo de entrega em PDF** (data/hora, CPF mascarado, item, matrícula do atendente).
Acesso em `/painel/entregas` (perfil *Operador de ponto*). Detalhes, decisões de segurança e rastreabilidade dos
critérios de aceitação em [`docs/ENTREGA_COM_RESPALDO_LEGAL.md`](docs/ENTREGA_COM_RESPALDO_LEGAL.md).
Testes: `pip install -r requirements-dev.txt && pytest`.

## Observações

- Hashes `scrypt:<salt>:<hex>` gerados pela versão Node são aceitos aqui (e vice-versa).
- Imagens: bucket privado do Supabase quando `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` existem;
  caso contrário, tabela `item_images`, sempre atrás de sessão.
- Diferenças de UI: páginas renderizadas no servidor (Jinja + CSS/JS simples) em vez de React/Tailwind;
  gráficos viram barras em HTML/CSS.
