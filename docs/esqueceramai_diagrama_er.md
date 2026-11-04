# EsqueceramAI — Diagrama Entidade-Relacionamento

```mermaid
erDiagram
    USUARIO ||--o| PERFIL : possui
    USUARIO ||--o{ DISPOSITIVO_FCM : "registra"
    USUARIO ||--o{ ITEM : "cadastra"
    USUARIO ||--o{ NOTIFICACAO : "recebe"
    USUARIO ||--o{ RECOMPENSA : "é beneficiário"
    USUARIO ||--o{ POSTO_OPERADOR : "opera"
    USUARIO ||--o{ HISTORICO_EVENTO : "origina"

    POSTO_COLETA ||--o{ POSTO_OPERADOR : "tem"
    POSTO_COLETA |o--o{ ITEM : "recebe"
    POSTO_COLETA |o--o{ RECUPERACAO : "retirada em"

    ITEM ||--o{ MATCH : "perdido participa"
    ITEM ||--o{ MATCH : "encontrado participa"
    MATCH ||--o| RECUPERACAO : "gera"
    MATCH |o--o{ NOTIFICACAO : "referencia"
    RECUPERACAO |o--o{ RECOMPENSA : "origina"

    USUARIO {
        bigint id PK
        varchar nome
        varchar email UK
        varchar senha_hash
        papel_usuario papel
        boolean ativo
    }
    PERFIL {
        bigint usuario_id PK, FK
        varchar telefone
        text foto_url
    }
    DISPOSITIVO_FCM {
        bigint id PK
        bigint usuario_id FK
        text token UK
        plataforma plataforma
    }
    POSTO_COLETA {
        bigint id PK
        varchar nome
        text endereco
        numeric latitude
        numeric longitude
        boolean ativo
    }
    POSTO_OPERADOR {
        bigint posto_id PK, FK
        bigint usuario_id PK, FK
    }
    ITEM {
        bigint id PK
        bigint usuario_id FK
        tipo_registro tipo_registro "PERDIDO | ENCONTRADO"
        categoria_item categoria "ELETRONICO | DOCUMENTO | ACESSORIO"
        text descricao
        varchar cor
        varchar marca
        varchar modelo
        jsonb atributos "específicos da categoria"
        text localizacao
        date data_ocorrencia
        text imagem_url "Firebase Storage"
        status_item status
        bigint posto_id FK
        tsvector busca "gerada"
    }
    MATCH {
        bigint id PK
        bigint item_perdido_id FK
        bigint item_encontrado_id FK
        numeric score "0 a 1"
        status_match status
        timestamptz decidido_em
    }
    RECUPERACAO {
        bigint id PK
        bigint match_id FK, UK
        bigint item_encontrado_id FK
        bigint posto_id FK
        status_recuperacao status
        timestamptz reservada_em
        timestamptz retirada_em
        timestamptz devolvida_em
    }
    RECOMPENSA {
        bigint id PK
        bigint beneficiario_id FK
        bigint recuperacao_id FK
        origem_recompensa origem
        int pontos
        status_recompensa status
    }
    NOTIFICACAO {
        bigint id PK
        bigint usuario_id FK
        tipo_notificacao tipo
        bigint match_id FK
        boolean lida
    }
    HISTORICO_EVENTO {
        bigint id PK
        varchar entidade
        bigint entidade_id
        varchar evento
        bigint usuario_id FK
        jsonb dados
    }
```

## Regras garantidas pelo banco

| Regra | Como é garantida |
|---|---|
| Match liga um item PERDIDO a um ENCONTRADO | FK composta `(id, tipo_registro)` |
| Só item ENCONTRADO vai para posto de coleta | `CHECK ck_item_posto_so_encontrado` |
| Documento exige `tipo_documento` | `CHECK ck_item_documento` |
| Um item não tem 2 recuperações ativas | Índice único parcial `ux_recuperacao_item_ativa` |
| Reserva atômica e sem concorrência | Função `reservar_item()` com `FOR UPDATE` |
| Mesmo par perdido/encontrado não repete | `UNIQUE (item_perdido_id, item_encontrado_id)` |
| Pontuação do usuário | View `pontuacao_usuario` (soma de `recompensa.pontos`) |
