# Entrega da Sprint I

Documento de encerramento da Sprint 1 do projeto **Esqueceram AI**, desenvolvido para a
disciplina de Engenharia de Software II da UFPI.

| Item | Valor |
|:---|:---|
| Sprint | 1 |
| Período | 15/10/2026 a 27/10/2026 |
| Líder / Scrum Master | Arthur Rabelo |
| Product Owner | Cauã Martins |
| Equipe | Arthur Rabelo, Cauã Martins, Kauan Saraiva, Samara Feitosa |
| Versão entregue | 1.0.0 |

---

## 1. Objetivo

Entregar a base funcional do núcleo de itens perdidos e encontrados: cadastro e busca de
itens, gestão de pontos de coleta e um ambiente de desenvolvimento reproduzível.

## 2. Escopo entregue

### 2.1 Histórias de usuário

| História | Entrega | Issue |
|:---|:---|:---|
| US01 — Perdi um item | Busca de itens por palavra-chave, tipo, categoria e status | #3, #11 |
| US02 — Encontrei um item | Cadastro de item com descrição, características, foto e ponto de coleta | #5, #9 |
| US03 — Ponto de coleta | Cadastro e listagem de pontos de coleta | #13, #14, #15 |
| US06 — Configuração do ambiente | Ambiente local containerizado com API, PostgreSQL e frontend | #54 |

### 2.2 Issues atendidas

- **#9** — `POST /api/itens` para cadastro de item, com upload de imagem.
- **#11** — `GET /api/itens` com filtros de busca textual e por status, tipo, categoria e ponto.
- **#3 / #5 / #12 / #10** — telas de busca, de cadastro de item encontrado e de item perdido.
- **#13 / #14 / #15** — cadastro de ponto de coleta, no backend e na interface.
- **#54** — ambiente local com Docker Compose.

## 3. Arquitetura

```
frontend (Nginx, :8080)
    │  proxy /api
    ▼
api (Flask + Gunicorn, :5000)
    │
    ▼
PostgreSQL 16 (:5432, volume postgres_data)
```

- O frontend é servido estático pelo Nginx, que repassa `/api/` para o serviço `api`,
  eliminando CORS e URLs fixas no JavaScript.
- A API usa `psycopg2` com acesso direto ao schema definido em `backend/sql/schema.sql`.
- As imagens ficam em um volume Docker (`uploads`) e são servidas por `/api/uploads/<arquivo>`.

## 4. Endpoints da API

| Método | Rota | Descrição |
|:---|:---|:---|
| GET | `/` | Status da API |
| GET | `/api/health` | Healthcheck |
| POST | `/api/itens` | Cadastra item (JSON ou `multipart/form-data` com imagem) |
| GET | `/api/itens` | Lista e busca itens |
| GET | `/api/itens/<id>` | Detalhe de um item |
| POST | `/api/postos` | Cadastra ponto de coleta |
| GET | `/api/postos` | Lista pontos de coleta |
| GET | `/api/uploads/<arquivo>` | Serve a imagem enviada |

### Filtros de `GET /api/itens`

| Parâmetro | Valores | Efeito |
|:---|:---|:---|
| `q` | texto livre | Busca textual em português (descrição, cor, marca, modelo) |
| `tipo_registro` | `PERDIDO`, `ENCONTRADO` | Filtra pelo tipo |
| `categoria` | `ELETRONICO`, `DOCUMENTO`, `ACESSORIO` | Filtra pela categoria |
| `status` | `ABERTO`, `RESERVADO`, `DEVOLVIDO`, `ARQUIVADO` | Filtra pelo status |
| `posto_id` | inteiro | Filtra pelo ponto de coleta |
| `limite` / `offset` | inteiro | Paginação (padrão 50, máximo 200) |

### Regras de validação

- `tipo_registro`, `categoria` e `descricao` são obrigatórios.
- Itens `DOCUMENTO` exigem `atributos.tipo_documento`.
- Apenas itens `ENCONTRADO` podem ser associados a um ponto de coleta.
- Latitude deve estar entre -90 e 90; longitude, entre -180 e 180.
- Imagens aceitas: `png`, `jpg`, `jpeg`, `gif`, `webp`, até 5 MB.

## 5. Ambiente de desenvolvimento

```bash
docker compose up --build
```

- Frontend: <http://localhost:8080>
- API: <http://localhost:5000>
- PostgreSQL: `localhost:5432` (volume `postgres_data`)

O schema é aplicado automaticamente na primeira execução do banco, a partir de
`backend/sql/schema.sql`. A API só inicia depois que o healthcheck do PostgreSQL responde.

## 6. Qualidade

- **14 testes automatizados** dos endpoints, cobrindo os caminhos de sucesso e as validações
  de erro, executados sem dependência de banco.
- Testes de integração do banco em `backend/tests/test_db.py`, executados quando há um
  PostgreSQL local configurado.
- Integração contínua no GitHub Actions: validação de sintaxe, execução da suíte e lint de YAML.

## 7. Dívida técnica assumida

Os itens abaixo estavam planejados para a Sprint 1 e foram replanejados para a Sprint 2,
conforme registrado na retrospectiva da sprint:

- Validação de propriedade por pergunta de segurança (US04).
- Termo de retirada com CPF e assinatura digital (US05).
- Controle de inventário e localização física no posto (US07).
- Política de caducidade e descarte (US08).
- Notificação automática de match (US09).
- Filtros de pesquisa por localidade (US10).
- Autenticação de usuários — até então, o cadastro usa um usuário padrão
  (`anonimo@esqueceram.ai`), configurável por `EMAIL_USUARIO_PADRAO`.

## 8. Como verificar

```bash
docker compose up --build
```

Depois, em <http://localhost:8080>:

1. Na aba **Ponto de coleta**, cadastre um ponto.
2. Na aba **Encontrei um item**, cadastre um item com foto e o ponto criado.
3. Na aba **Buscar item**, filtre por palavra-chave e confira o resultado.

Alternativamente, sem o frontend:

```bash
curl http://localhost:5000/api/health
curl "http://localhost:5000/api/itens?q=celular&status=ABERTO"
```
