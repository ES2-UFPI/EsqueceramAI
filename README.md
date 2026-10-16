# Esqueceram AI

Plataforma inteligente para registro, busca e recuperação de itens perdidos. Projeto desenvolvido para a disciplina de Engenharia de Software II
da UFPI.

Este documento descreve a configuração do ambiente de desenvolvimento do
backend do projeto.

## Tecnologias

- Python 3.10 ou superior;
- Flask;
- PostgreSQL;
- Firebase Storage para armazenamento das imagens;
- Git.

O backend segue a organização:

```text
Controller -> Service -> Repository -> PostgreSQL
                         |
                         -> Firebase Storage
```

O cliente não acessa diretamente o PostgreSQL. As imagens são armazenadas no
Firebase Storage, enquanto o banco mantém apenas a referência necessária para
acessá-las.

## Pré-requisitos

Instale os seguintes programas:

- [Git para Windows](https://git-scm.com/install/windows);
- [Python para Windows](https://www.python.org/downloads/windows/);
- [PostgreSQL](https://www.postgresql.org/download/);
- uma conta ou projeto no [Firebase](https://firebase.google.com/).

Verifique a instalação no PowerShell:

```powershell
git --version
py --version
py -m pip --version
psql --version
```

## Clonar o projeto

```powershell
git clone https://github.com/ES2-UFPI/EsqueceramAI.git
Set-Location .\EsqueceramAI
```

## Criar o ambiente virtual

O ambiente virtual mantém as dependências do projeto isoladas das bibliotecas
instaladas globalmente no computador.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Se o PowerShell bloquear a ativação dos scripts, execute o comando abaixo uma
vez para o usuário atual e tente ativar o ambiente novamente:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Quando a ativação funcionar, o terminal exibirá `(.venv)` no início da linha.

## Instalar as dependências

Quando o projeto possuir o arquivo `requirements.txt`, instale as dependências
com:

```powershell
python -m pip install -r requirements.txt
```

Enquanto esse arquivo ainda não estiver disponível, instale as dependências
base do backend:

```powershell
python -m pip install Flask Flask-Cors Flask-SQLAlchemy "psycopg[binary]" firebase-admin python-dotenv
```

Após alterar as dependências do projeto, atualize o arquivo:

```powershell
python -m pip freeze > requirements.txt
```

## Configurar o PostgreSQL

Crie um banco de dados de desenvolvimento e um usuário para a aplicação. Por
exemplo, no `psql`:

```sql
CREATE USER esqueceram_ai WITH PASSWORD 'defina-uma-senha-local';
CREATE DATABASE esqueceram_ai OWNER esqueceram_ai;
```

Não use essa senha em produção e não a publique no repositório.

## Configurar o Firebase Storage

1. Crie ou selecione um projeto no Firebase.
2. Ative o Firebase Storage.
3. Gere uma credencial de serviço para o backend.
4. Armazene o arquivo da credencial fora do controle de versão.

O caminho do arquivo e as configurações do banco devem ser informados por
variáveis de ambiente. Um arquivo `.env` local pode conter, por exemplo:

```dotenv
FLASK_ENV=development
DATABASE_URL=postgresql+psycopg://esqueceram_ai:senha-local@localhost:5432/esqueceram_ai
GOOGLE_APPLICATION_CREDENTIALS=C:\caminho\seguro\firebase-service-account.json
FIREBASE_STORAGE_BUCKET=seu-projeto.firebasestorage.app
```

Nunca faça commit de `.env`, credenciais do Firebase, tokens ou senhas.
Mantenha somente nomes de variáveis e valores fictícios em um eventual arquivo
`.env.example`.

## Executar o backend

Com o ambiente virtual ativado, execute a aplicação Flask conforme o ponto de
entrada definido pelo projeto. Exemplos:

```powershell
python app.py
```

ou:

```powershell
python -m flask --app app run --debug
```

Por padrão, a aplicação ficará disponível em
`http://127.0.0.1:5000`.

## Testar a API

O endpoint de cadastro de itens deve seguir o contrato definido pela equipe.
Para o cadastro com imagem, a requisição utilizará `multipart/form-data`.
Exemplo:

```powershell
curl.exe -X POST http://127.0.0.1:5000/api/itens `
  -F "tipo_registro=PERDIDO" `
  -F "descricao=Celular preto com capa azul" `
  -F "categoria=ELETRONICO" `
  -F "localizacao=Biblioteca Central" `
  -F "data_ocorrencia=2026-10-16" `
  -F "imagem=@C:\caminho\celular.jpg"
```

Uma implementação concluída deve retornar `201 Created` para um cadastro
válido e respostas de erro apropriadas para dados inválidos ou imagens não
aceitas.

## Branches e contribuição

O fluxo de branches, commits e Pull Requests está documentado em
[CONTRIBUTING.md](CONTRIBUTING.md).

Não faça commits diretamente nas branches `main` ou `dev`. Crie uma branch
específica para cada tarefa e abra um Pull Request direcionado para `dev`.

## Documentação adicional

- [Wiki do projeto](https://github.com/ES2-UFPI/EsqueceramAI/wiki);
- [Definição tecnológica](https://github.com/ES2-UFPI/EsqueceramAI/wiki/Defini%C3%A7%C3%A3o-Tecnol%C3%B3gica);
- [Preparação do ambiente](https://github.com/ES2-UFPI/EsqueceramAI/wiki/Preparando-o-ambiente-de-desenvolvimento);
- [Visão arquitetural da API](https://github.com/ES2-UFPI/EsqueceramAI/wiki/API-%E2%80%94-Vis%C3%A3o-Arquitetural).
