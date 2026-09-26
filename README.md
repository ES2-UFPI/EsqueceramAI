# Esqueceram AI 🔍

Plataforma inteligente para registro, busca e recuperação de itens perdidos e achados. Projeto desenvolvido para a disciplina de Engenharia de Software II da UFPI.

Este documento, momentaneamente, estabelece o padrão de uso do Git, criação de branches, commits e Pull Requests (PRs) para o desenvolvimento do **Esqueceram AI**. É fundamental que todos sigam estes passos para manter a integridade do código e evitar conflitos.

---

## 🛠️ 1. Configuração Inicial e Clonagem

Antes de começar a contribuir, certifique-se de que seu Git está configurado corretamente com seu nome e email institucionais/profissionais.

```bash
# Configurar nome
git config --global user.name "Seu Nome e Sobrenome"

# Configurar email
git config --global user.email "seuemail@exemplo.com"
```

Em seguida, clone o repositório para a sua máquina local e entre na pasta do projeto:

```bash
# Clonar o repositório
git clone https://github.com/ES2-UFPI/EsqueceramAI.git

# Entrar no diretório
cd EsqueceramAI
```

---

## 🌱 2. Fluxo de Trabalho (Branching)

**NUNCA** faça commits diretamente nas branches `main` ou `dev`. Todo o desenvolvimento deve ocorrer em branches isoladas e enviadas via Pull Request.

### Passo 2.1: Atualizar o repositório e ir para a branch dev
A branch `dev` é a nossa branch principal de integração. **SEMPRE** crie suas novas branches a partir dela, devidamente atualizada.

```bash
# Baixa as informações e histórico mais recentes do repositório remoto
git fetch origin

# Atualiza a sua branch atual puxando as últimas alterações da branch dev
git pull origin dev
```

```bash
# Mudar para a branch de desenvolvimento
git checkout dev

# Puxar as atualizações mais recentes do servidor
git pull origin dev
```

### Passo 2.2: Criar sua branch de funcionalidade/correção
Crie uma nova branch para a tarefa em que você vai trabalhar. 
O padrão de nomenclatura obrigatório é: `tipo/nomedafuncionalidade#numerodaissue`

**Tipos comuns:**
- `feat/`: Para novas funcionalidades.
- `fix/`: Para correção de bugs.
- `docs/`: Para documentação.

**Exemplo prático:** Se você está trabalhando na funcionalidade de login que corresponde à Issue número 12:

```bash
git checkout -b feat/login-usuario#12
```

---

## 💾 3. Salvando suas Alterações (Add, Commit e Push)

À medida que você for desenvolvendo sua funcionalidade, salve seu progresso realizando commits com mensagens claras e descritivas sobre o que foi feito.

```bash
# Adicionar os arquivos modificados (use o '.' para todos, ou especifique o arquivo)
git add .

# Criar o commit com uma mensagem descritiva
git commit -m "feat: adiciona validacao de email no formulario de login"

# Enviar a sua branch local para o repositório remoto no GitHub
git push origin feat/login-usuario#12
```

---

## 🔄 4. Criando um Pull Request (PR)

Quando sua funcionalidade estiver finalizada e "commitada" no GitHub, você deve solicitar que seu código seja mesclado na branch principal de desenvolvimento (`dev`).

1. Acesse a página do repositório no GitHub: https://github.com/ES2-UFPI/EsqueceramAI
2. Você verá um aviso amarelo sugerindo criar um Pull Request (PR) para a sua branch recém-enviada. Clique em **Compare & pull request**.
> 3. **⚠️ ATENÇÃO MÁXIMA AQUI⚠️:** Como nosso repositório está dentro de uma organização da disciplina, o GitHub pode tentar apontar o Pull Request (PR) para o repositório original (caso seja um fork) ou para a branch `main`. 
  > - Certifique-se de que o **base repository** seja `ES2-UFPI/EsqueceramAI`.
  > - Certifique-se de que a **base branch** (para onde o código vai) seja a **`dev`**.
  > - A **compare branch** (de onde o código vem) será a sua branch (`feat/...`).
4. No título e na descrição do Pull Request (PR), referencie a issue que ele resolve (ex: `Closes #12`). Isso fará com que o GitHub feche a issue automaticamente quando o Pull Request (PR) for aprovado.
5. Clique em **Create pull request**.

---

## 🤖 5. Integração Contínua (CI) e Qualidade

Temos um workflow de Integração Contínua (CI) configurado no repositório. O que isso significa na prática?

- Toda vez que você abrir um Pull Request ou fizer um novo push para um Pull Request (PR) aberto, o GitHub Actions executará automaticamente um pipeline de verificação (build e testes).
- A mescla (merge) no Pull Request (PR) será bloqueada automaticamente se o seu código contiver erros de compilação ou se os testes falharem.
> - **Instrução:** Teste e compile seu código localmente antes de fazer o `git push`. Evite poluir o histórico de commits do Pull Request (PR).

---

## 🛡️ 6. Boas Práticas e Prevenção de Erros

Para evitar dor de cabeça e conflitos de código, siga estas regras:

1. **Faça Commits Pequenos e Frequentes:** Não deixe para fazer um commit gigante no final da semana. Faça commits lógicos a cada avanço significativo.
2. **Sincronize sua Branch Regularmente:** Se você estiver trabalhando na mesma branch por vários dias, outras pessoas podem ter feito merge na `dev`. Para evitar conflitos enormes no final, puxe as atualizações da dev para a sua branch periodicamente:

```bash
# Dentro da sua branch de trabalho (feat/...):
git pull origin dev
```

Resolva os pequenos conflitos (se houver) localmente antes de continuar o trabalho.

3. **Não commite arquivos de configuração pessoal ou dependências:** O arquivo `.gitignore` cuidará disso, mas preste atenção para não usar `git add -f` ou comitar pastas como `node_modules`, `target`, `.vscode` ou `.idea`.