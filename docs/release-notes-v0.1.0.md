# Esqueceram AI v0.1.0 — Sprint I

**Iteração I (15/10 a 27/10/2026) · Engenharia de Software II · UFPI**

Primeira versão do Esqueceram AI. O cadastro de um item encontrado e a busca por um item
perdido deixam de ser um formulário em papel e passam a acontecer dentro de uma aplicação
web, com backend, banco de dados e ambiente containerizado. Quem encontrou um objeto
descreve o que achou, anexa uma foto e indica em qual ponto de coleta deixou; quem perdeu
procura por palavra-chave e filtra por tipo, categoria e situação.

Esta versão cobre o núcleo do fluxo de itens perdidos e encontrados. A validação de
propriedade, o termo de retirada, a política de descarte e as notificações automáticas
entram nas próximas iterações.

---

## O que a versão entrega

### Busca de item perdido

A aba **Buscar item** concentra a consulta em uma única tela. O termo digitado é comparado
com descrição, cor, marca e modelo usando busca textual em português, então "celular azul"
encontra um item cadastrado como "Samsung Galaxy A54 azul" mesmo sem as palavras na mesma
ordem. Os filtros de tipo, categoria e situação combinam entre si e com o termo, e cada
resultado exibe a foto, a descrição, os atributos e o ponto de coleta onde o item está.

### Cadastro de item encontrado

A aba **Encontrei um item** recebe descrição, categoria, cor, marca, modelo, local onde o
objeto foi achado, data e coordenadas. Itens da categoria Documento pedem o tipo do
documento, e apenas itens encontrados podem ser associados a um ponto de coleta — a API
recusa a combinação contrária. A foto é enviada junto com o formulário e fica disponível
por uma rota própria da API.

### Pontos de coleta

A aba **Ponto de coleta** cadastra os locais onde os objetos ficam guardados, com nome,
endereço, coordenadas e horário de funcionamento. A lista de pontos alimenta o seletor do
formulário de cadastro, de modo que o item já é registrado com o destino correto.

### Ambiente reproduzível

A aplicação inteira sobe com um comando. O Docker Compose levanta o PostgreSQL, a API e o
frontend, com os dados do banco e as imagens enviadas em volumes persistentes. O schema é
criado na primeira subida do banco, e a API só inicia depois que o PostgreSQL responde ao
healthcheck.

---

## Novidades

- **Cadastro de item** ([#9](https://github.com/ES2-UFPI/EsqueceramAI/issues/9)):
  `POST /api/itens` aceita JSON ou `multipart/form-data` com imagem e valida tipo de
  registro, categoria, descrição, documento, ponto de coleta e coordenadas antes de
  gravar.
- **Listagem e busca de itens** ([#11](https://github.com/ES2-UFPI/EsqueceramAI/issues/11)):
  `GET /api/itens` combina busca textual com filtros de situação, tipo, categoria e ponto
  de coleta, com paginação por `limite` e `offset` e ordenação do mais recente para o mais
  antigo.
- **Detalhe de item**: `GET /api/itens/<id>` devolve um item com o nome do ponto de coleta
  associado.
- **Pontos de coleta** ([#13](https://github.com/ES2-UFPI/EsqueceramAI/issues/13),
  [#14](https://github.com/ES2-UFPI/EsqueceramAI/issues/14),
  [#15](https://github.com/ES2-UFPI/EsqueceramAI/issues/15)): `POST /api/postos` e
  `GET /api/postos` cadastram e listam os locais de guarda, consumidos pelo formulário de
  cadastro de item.
- **Upload de imagens**: a foto enviada é gravada em disco e servida por
  `GET /api/uploads/<arquivo>`, sem depender de serviço externo pago.
- **Interface web**: uma página com três abas — busca, cadastro e pontos de coleta — que
  consome a API pela própria origem, sem CORS e sem URL fixa no JavaScript.
- **Ambiente local com Docker Compose**
  ([#54](https://github.com/ES2-UFPI/EsqueceramAI/issues/54)): API, PostgreSQL 16 e
  frontend Nginx em uma rede única, com healthcheck do banco e volumes para dados e
  imagens.
- **Modelagem do banco**
  ([#8](https://github.com/ES2-UFPI/EsqueceramAI/issues/8)): schema PostgreSQL com tipos
  enumerados para papéis, categorias, situações e estados, e as entidades de usuário,
  perfil, dispositivo, ponto de coleta, item, match, recuperação, recompensa e
  notificação.

## Melhorias

- **Busca textual indexada**: a coluna `busca` é gerada automaticamente a partir de
  descrição, cor, marca e modelo, com índice GIN em português, e a API consulta essa
  coluna em vez de varrer a tabela.
- **Validação na borda**: tipo de registro, categoria e situação são conferidos contra
  listas fechadas; valores fora do domínio retornam 400 em vez de chegar ao banco.
- **Coordenadas conferidas**: latitude entre -90 e 90 e longitude entre -180 e 180, tanto
  no cadastro de item quanto no de ponto de coleta.
- **Upload restrito**: apenas `png`, `jpg`, `jpeg`, `gif` e `webp`, com limite de 5 MB,
  verificados pelo conteúdo lido — não pelo nome informado no cabeçalho.
- **Paginação limitada**: `limite` é limitado a 200 registros por requisição e nunca é
  menor que 1, o que impede uma consulta acidental de varrer a tabela inteira.
- **Frontend atrás do Nginx**: o Nginx serve os arquivos estáticos e repassa `/api/` para
  o serviço da API, o que elimina CORS e mantém um endereço único para quem usa.
- **Integração contínua**: o workflow valida a sintaxe do Python, executa a suíte de testes
  e confere o YAML das configurações a cada push e pull request.

## Correções

- **Listagem de itens quebrava por `NameError`**: a variável de erro usada em
  `GET /api/itens` não existia, e a rota falhava em vez de responder. Corrigido.
- **Frontend com URL fixa e CORS**: o JavaScript chamava a API por um endereço absoluto,
  o que quebrava ao publicar. Passou a usar caminho relativo pela mesma origem.
- **Imagens perdidas ao recriar o container**: o diretório de uploads ficava dentro do
  container e era descartado a cada recriação. Passou a residir em um volume Docker.
- **Schema não aplicado**: o banco subia vazio. Passou a aplicar `schema.sql` na primeira
  inicialização, pelo diretório de entrada do PostgreSQL.

## Outros

- **Documentação da entrega**: `docs/entrega-sprint-1.md` reúne escopo, arquitetura,
  endpoints, regras de validação e dívida técnica assumida.
- **Guia do ambiente**: `docs/docker-compose-guide.md` descreve subida, derrubada e
  diagnóstico dos serviços.
- **Diagrama entidade-relacionamento**: `docs/esqueceramai_diagrama_er.md` documenta o
  modelo de dados.
- **Padrão de contribuição**: `CONTRIBUTING.md` define o fluxo de branches por issue e o
  formato de commit e de pull request.
- **14 testes automatizados** dos endpoints, cobrindo os caminhos de sucesso e as
  validações de erro, executados sem depender de banco.
- **Deploy declarado**: `render.yaml` descreve o serviço da API para publicação no Render.

## Limitações conhecidas

- **Busca por foto não implementada.** A US01 prevê procurar o item "através de descrição
  e/ou foto". A versão entrega busca textual e filtros; o envio de foto funciona, mas não
  há comparação entre imagens.
- **Sem autenticação.** Os itens são atribuídos a um usuário padrão
  (`anonimo@esqueceram.ai`, configurável por `EMAIL_USUARIO_PADRAO`) e não há login nem
  perfis. Qualquer pessoa com acesso à aplicação vê e cadastra itens.
- **Validação de propriedade, termo de retirada, inventário físico, política de
  descarte, notificação de match e filtros por localidade** (US04, US05, US07, US08, US09
  e US10) foram replanejados para as iterações seguintes, conforme a retrospectiva.
- **Upload em disco local.** As imagens ficam no volume da máquina que roda a API; em
  produção, ainda é preciso apontar para um armazenamento externo.
- **O ambiente não foi validado de ponta a ponta nesta entrega.** A suíte de testes passa
  (14 de 14), mas a subida via Docker Compose não foi executada por falta do daemon Docker
  disponível no momento do fechamento.

## Como rodar

```bash
docker compose up --build
```

- Frontend: <http://localhost:8080>
- API: <http://localhost:5000>
- PostgreSQL: `localhost:5432` (volume `postgres_data`)

O passo a passo completo está no [guia do ambiente](https://github.com/ES2-UFPI/EsqueceramAI/blob/v0.1.0/docs/docker-compose-guide.md).

Para conferir o fluxo sem o frontend:

```bash
curl http://localhost:5000/api/health
curl "http://localhost:5000/api/itens?q=celular"
```

## Equipe

| Papel | Nome |
|:---|:---|
| Product Owner | [Cauã Martins](https://github.com/martincaua) |
| Scrum Master | [Arthur Rabelo](https://github.com/arthurabelo) |
| Desenvolvedor e Revisor | [Arthur Rabelo](https://github.com/arthurabelo) |
| Desenvolvedor e Revisor | [Cauã Martins](https://github.com/martincaua) |
| Desenvolvedor e Revisor | [Kauan Saraiva](https://github.com/kauansaraivva) |
| Desenvolvedor e Revisor | [Samara Feitosa](https://github.com/SamaraFS-tech) |

Planejamento, burndown e retrospectiva da iteração:
[Planejamento das Iterações](https://github.com/ES2-UFPI/EsqueceramAI/wiki/Planejamento-das-Itera%C3%A7%C3%B5es#sprint-1).
