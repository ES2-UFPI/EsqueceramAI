-- =====================================================================
-- Decisões principais:
--  * Item em TABELA ÚNICA (categoria + atributos específicos em JSONB),
--    para que busca, filtros e match não precisem de JOINs.
--  * Fotos ficam no Firebase Storage; o banco guarda só a URL.
--  * Match só liga item PERDIDO a item ENCONTRADO (garantido por FK composta).
--  * Um item encontrado não pode ter duas recuperações ativas ao mesmo
--    tempo (índice único parcial + função reservar_item com lock).
-- =====================================================================

BEGIN;
-- ---------------------------------------------------------------------
-- Tipos enumerados
-- ---------------------------------------------------------------------
CREATE TYPE papel_usuario        AS ENUM ('USUARIO', 'OPERADOR_POSTO', 'ADMIN');
CREATE TYPE tipo_registro        AS ENUM ('PERDIDO', 'ENCONTRADO');
CREATE TYPE categoria_item       AS ENUM ('ELETRONICO', 'DOCUMENTO', 'ACESSORIO');
CREATE TYPE status_item          AS ENUM ('ABERTO', 'RESERVADO', 'DEVOLVIDO', 'ARQUIVADO');
CREATE TYPE status_match         AS ENUM ('PENDENTE', 'CONFIRMADO', 'RECUSADO');
CREATE TYPE status_recuperacao   AS ENUM ('CONFIRMADA', 'RESERVADA', 'RETIRADA', 'DEVOLVIDA', 'CANCELADA');
CREATE TYPE origem_recompensa    AS ENUM ('REGRA_PONTOS', 'OFERTA_PROPRIETARIO');
CREATE TYPE status_recompensa    AS ENUM ('PENDENTE', 'RECEBIDA', 'CANCELADA');
CREATE TYPE tipo_notificacao     AS ENUM ('MATCH_IDENTIFICADO', 'RECUPERACAO_ATUALIZADA', 'ITEM_ATUALIZADO', 'RECOMPENSA');
CREATE TYPE plataforma_dispositivo AS ENUM ('WEB', 'ANDROID', 'IOS');
-- ---------------------------------------------------------------------
-- Utilitário: atualiza coluna atualizado_em
-- ---------------------------------------------------------------------
CREATE FUNCTION set_atualizado_em() RETURNS trigger AS $$
BEGIN
    NEW.atualizado_em := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
-- ---------------------------------------------------------------------
-- Módulo: Acesso e Perfil
-- ---------------------------------------------------------------------
CREATE TABLE usuario (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome           VARCHAR(150)  NOT NULL,
    email          VARCHAR(254)  NOT NULL,
    senha_hash     VARCHAR(255)  NOT NULL,          -- nunca guardar senha em texto
    papel          papel_usuario NOT NULL DEFAULT 'USUARIO',
    ativo          BOOLEAN       NOT NULL DEFAULT TRUE,
    criado_em      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    atualizado_em  TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_usuario_email ON usuario (lower(email));
CREATE TRIGGER trg_usuario_atualizado BEFORE UPDATE ON usuario
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

CREATE TABLE perfil (
    usuario_id     BIGINT PRIMARY KEY REFERENCES usuario(id) ON DELETE CASCADE,
    telefone       VARCHAR(20),
    foto_url       TEXT,
    atualizado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_perfil_atualizado BEFORE UPDATE ON perfil
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();
-- Tokens do Firebase Cloud Messaging (um usuário pode ter vários dispositivos)
CREATE TABLE dispositivo_fcm (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id     BIGINT NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    token          TEXT   NOT NULL UNIQUE,
    plataforma     plataforma_dispositivo NOT NULL DEFAULT 'WEB',
    criado_em      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultimo_uso_em  TIMESTAMPTZ
);
CREATE INDEX ix_dispositivo_usuario ON dispositivo_fcm (usuario_id);
-- ---------------------------------------------------------------------
-- Módulo: Postos de Coleta
-- ---------------------------------------------------------------------
CREATE TABLE posto_coleta (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome           VARCHAR(150) NOT NULL,
    endereco       TEXT         NOT NULL,
    latitude       NUMERIC(9,6) CHECK (latitude  BETWEEN -90  AND 90),
    longitude      NUMERIC(9,6) CHECK (longitude BETWEEN -180 AND 180),
    horario_funcionamento TEXT,
    ativo          BOOLEAN      NOT NULL DEFAULT TRUE,
    criado_em      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
-- Quem opera cada posto (registrar recebimento / retirada)
CREATE TABLE posto_operador (
    posto_id       BIGINT NOT NULL REFERENCES posto_coleta(id) ON DELETE CASCADE,
    usuario_id     BIGINT NOT NULL REFERENCES usuario(id)      ON DELETE CASCADE,
    PRIMARY KEY (posto_id, usuario_id)
);
-- ---------------------------------------------------------------------
-- Módulo: Gestão de Itens
-- Atributos específicos por categoria (JSONB), conforme as subclasses:
--   ELETRONICO: marca, modelo  -> colunas próprias (usadas em filtros)
--   DOCUMENTO : {"tipo_documento": "...", "orgao_emissor": "..."}
--   ACESSORIO : {"material": "..."}  (marca na coluna própria)
-- ---------------------------------------------------------------------
CREATE TABLE item (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id       BIGINT NOT NULL REFERENCES usuario(id),
    tipo_registro    tipo_registro  NOT NULL,
    categoria        categoria_item NOT NULL,
    descricao        TEXT           NOT NULL,
    cor              VARCHAR(40),
    marca            VARCHAR(80),
    modelo           VARCHAR(80),
    atributos        JSONB          NOT NULL DEFAULT '{}'::jsonb,
    localizacao      TEXT,                              -- texto livre ("Bloco 5, CCN")
    latitude         NUMERIC(9,6) CHECK (latitude  BETWEEN -90  AND 90),
    longitude        NUMERIC(9,6) CHECK (longitude BETWEEN -180 AND 180),
    data_ocorrencia  DATE           NOT NULL DEFAULT CURRENT_DATE,  -- quando perdeu / achou
    imagem_url       TEXT,                              -- Firebase Storage
    status           status_item    NOT NULL DEFAULT 'ABERTO',
    posto_id         BIGINT REFERENCES posto_coleta(id),
    criado_em        TIMESTAMPTZ    NOT NULL DEFAULT now(),
    atualizado_em    TIMESTAMPTZ    NOT NULL DEFAULT now(),

    -- necessária para a FK composta da tabela match
    CONSTRAINT ux_item_id_tipo UNIQUE (id, tipo_registro),

    CONSTRAINT ck_item_atributos_objeto CHECK (jsonb_typeof(atributos) = 'object'),
    -- só item ENCONTRADO é entregue em posto de coleta
    CONSTRAINT ck_item_posto_so_encontrado CHECK (posto_id IS NULL OR tipo_registro = 'ENCONTRADO'),
    -- documento precisa informar o tipo
    CONSTRAINT ck_item_documento CHECK (categoria <> 'DOCUMENTO' OR atributos ? 'tipo_documento'),

    -- busca textual em português (descrição, cor, marca, modelo)
    busca tsvector GENERATED ALWAYS AS (
        to_tsvector('portuguese',
            coalesce(descricao,'') || ' ' || coalesce(cor,'') || ' ' ||
            coalesce(marca,'')     || ' ' || coalesce(modelo,''))
    ) STORED
);
CREATE TRIGGER trg_item_atualizado BEFORE UPDATE ON item
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

CREATE INDEX ix_item_busca        ON item USING GIN (busca);
CREATE INDEX ix_item_atributos    ON item USING GIN (atributos jsonb_path_ops);
CREATE INDEX ix_item_candidatos   ON item (tipo_registro, status, categoria, data_ocorrencia DESC);
CREATE INDEX ix_item_usuario      ON item (usuario_id);
CREATE INDEX ix_item_posto        ON item (posto_id) WHERE posto_id IS NOT NULL;
CREATE INDEX ix_item_cor          ON item (lower(cor));
CREATE INDEX ix_item_marca        ON item (lower(marca));
-- ---------------------------------------------------------------------
-- Módulo: Match
-- FKs compostas garantem: item_perdido_id aponta p/ item PERDIDO e
-- item_encontrado_id aponta p/ item ENCONTRADO.
-- ---------------------------------------------------------------------
CREATE TABLE match (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_perdido_id     BIGINT NOT NULL,
    item_encontrado_id  BIGINT NOT NULL,
    tipo_perdido        tipo_registro NOT NULL DEFAULT 'PERDIDO'    CHECK (tipo_perdido    = 'PERDIDO'),
    tipo_encontrado     tipo_registro NOT NULL DEFAULT 'ENCONTRADO' CHECK (tipo_encontrado = 'ENCONTRADO'),
    score               NUMERIC(5,4)  NOT NULL CHECK (score BETWEEN 0 AND 1),
    status              status_match  NOT NULL DEFAULT 'PENDENTE',
    criado_em           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    decidido_em         TIMESTAMPTZ,

    CONSTRAINT fk_match_perdido    FOREIGN KEY (item_perdido_id,    tipo_perdido)
        REFERENCES item (id, tipo_registro),
    CONSTRAINT fk_match_encontrado FOREIGN KEY (item_encontrado_id, tipo_encontrado)
        REFERENCES item (id, tipo_registro),
    CONSTRAINT ux_match_par UNIQUE (item_perdido_id, item_encontrado_id),
    -- necessária para a FK composta da tabela recuperacao
    CONSTRAINT ux_match_id_encontrado UNIQUE (id, item_encontrado_id)
);
CREATE INDEX ix_match_perdido    ON match (item_perdido_id);
CREATE INDEX ix_match_encontrado ON match (item_encontrado_id);
CREATE INDEX ix_match_pendentes  ON match (score DESC) WHERE status = 'PENDENTE';
-- ---------------------------------------------------------------------
-- Módulo: Recuperação
-- ---------------------------------------------------------------------
CREATE TABLE recuperacao (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id            BIGINT NOT NULL,
    item_encontrado_id  BIGINT NOT NULL,   -- redundante de propósito: sustenta o índice parcial abaixo
    posto_id            BIGINT REFERENCES posto_coleta(id),
    status              status_recuperacao NOT NULL DEFAULT 'CONFIRMADA',
    confirmada_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    reservada_em        TIMESTAMPTZ,
    retirada_em         TIMESTAMPTZ,
    devolvida_em        TIMESTAMPTZ,
    observacao          TEXT,

    CONSTRAINT fk_recuperacao_match FOREIGN KEY (match_id, item_encontrado_id)
        REFERENCES match (id, item_encontrado_id),
    CONSTRAINT ux_recuperacao_match UNIQUE (match_id)
);
-- Regra: um item encontrado não pode ter 2 recuperações ativas ao mesmo tempo
CREATE UNIQUE INDEX ux_recuperacao_item_ativa
    ON recuperacao (item_encontrado_id)
    WHERE status IN ('CONFIRMADA', 'RESERVADA', 'RETIRADA');
-- ---------------------------------------------------------------------
-- Módulo: Recompensas (a pontuação é a soma dos pontos — ver view)
-- ---------------------------------------------------------------------
CREATE TABLE recompensa (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    beneficiario_id       BIGINT NOT NULL REFERENCES usuario(id),
    recuperacao_id        BIGINT REFERENCES recuperacao(id),
    origem                origem_recompensa NOT NULL,
    pontos                INTEGER NOT NULL DEFAULT 0 CHECK (pontos >= 0),
    descricao             TEXT,                                  -- ex.: recompensa oferecida pelo dono
    status                status_recompensa NOT NULL DEFAULT 'PENDENTE',
    criado_em             TIMESTAMPTZ NOT NULL DEFAULT now(),
    recebida_em           TIMESTAMPTZ,
    CONSTRAINT ck_recompensa_conteudo CHECK (pontos > 0 OR descricao IS NOT NULL)
);
CREATE INDEX ix_recompensa_beneficiario ON recompensa (beneficiario_id);
CREATE INDEX ix_recompensa_recuperacao  ON recompensa (recuperacao_id);

CREATE VIEW pontuacao_usuario AS
SELECT u.id AS usuario_id,
       u.nome,
       COALESCE(SUM(r.pontos) FILTER (WHERE r.status <> 'CANCELADA'), 0) AS pontos_total
FROM usuario u
LEFT JOIN recompensa r ON r.beneficiario_id = u.id
GROUP BY u.id, u.nome;
-- ---------------------------------------------------------------------
-- Módulo: Notificações
-- ---------------------------------------------------------------------
CREATE TABLE notificacao (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id     BIGINT NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    tipo           tipo_notificacao NOT NULL,
    titulo         VARCHAR(150) NOT NULL,
    corpo          TEXT NOT NULL,
    match_id       BIGINT REFERENCES match(id) ON DELETE SET NULL,
    dados          JSONB NOT NULL DEFAULT '{}'::jsonb,
    lida           BOOLEAN NOT NULL DEFAULT FALSE,
    criada_em      TIMESTAMPTZ NOT NULL DEFAULT now(),
    enviada_fcm_em TIMESTAMPTZ
);
CREATE INDEX ix_notificacao_usuario ON notificacao (usuario_id, lida, criada_em DESC);
-- ---------------------------------------------------------------------
-- Histórico de eventos (alimentado pelo HistoryObserver)
-- ---------------------------------------------------------------------
CREATE TABLE historico_evento (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entidade       VARCHAR(30) NOT NULL,        -- 'item', 'match', 'recuperacao', ...
    entidade_id    BIGINT      NOT NULL,
    evento         VARCHAR(60) NOT NULL,        -- 'MatchIdentificado', 'ItemReservado', ...
    usuario_id     BIGINT REFERENCES usuario(id) ON DELETE SET NULL,
    dados          JSONB NOT NULL DEFAULT '{}'::jsonb,
    criado_em      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_historico_entidade ON historico_evento (entidade, entidade_id, criado_em DESC);
-- ---------------------------------------------------------------------
-- Operação atômica: confirmar propriedade e reservar o item
-- (POST /api/matches/{id}/confirmar). O lock evita reservas concorrentes.
-- ---------------------------------------------------------------------
CREATE FUNCTION reservar_item(p_match_id BIGINT, p_posto_id BIGINT DEFAULT NULL)
RETURNS BIGINT AS $$
DECLARE
    v_encontrado BIGINT;
    v_perdido    BIGINT;
    v_status     status_item;
    v_rec_id     BIGINT;
BEGIN
    SELECT item_encontrado_id, item_perdido_id
      INTO v_encontrado, v_perdido
      FROM match
     WHERE id = p_match_id AND status = 'PENDENTE'
       FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Match % não existe ou já foi decidido', p_match_id;
    END IF;

    SELECT status INTO v_status FROM item WHERE id = v_encontrado FOR UPDATE;
    IF v_status <> 'ABERTO' THEN
        RAISE EXCEPTION 'Item % não está disponível (status %)', v_encontrado, v_status
            USING ERRCODE = 'unique_violation';
    END IF;

    UPDATE match SET status = 'CONFIRMADO', decidido_em = now() WHERE id = p_match_id;
    UPDATE item  SET status = 'RESERVADO' WHERE id IN (v_encontrado, v_perdido);

    INSERT INTO recuperacao (match_id, item_encontrado_id, posto_id, status, reservada_em)
    VALUES (p_match_id, v_encontrado, p_posto_id, 'RESERVADA', now())
    RETURNING id INTO v_rec_id;

    RETURN v_rec_id;
END;
$$ LANGUAGE plpgsql;

COMMIT;