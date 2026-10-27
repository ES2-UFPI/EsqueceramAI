import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    BigInteger, Boolean, Computed, Date, DateTime, Enum, ForeignKey,
    ForeignKeyConstraint, Identity, Integer, Numeric, String, Text, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from extensions import db
# ---------------------------------------------------------------------------
# Enums (os valores precisam ser idênticos aos tipos criados no schema.sql)
# ---------------------------------------------------------------------------
class PapelUsuario(enum.Enum):
    USUARIO = "USUARIO"
    OPERADOR_POSTO = "OPERADOR_POSTO"
    ADMIN = "ADMIN"

class TipoRegistro(enum.Enum):
    PERDIDO = "PERDIDO"
    ENCONTRADO = "ENCONTRADO"

class CategoriaItem(enum.Enum):
    ELETRONICO = "ELETRONICO"
    DOCUMENTO = "DOCUMENTO"
    ACESSORIO = "ACESSORIO"

class StatusItem(enum.Enum):
    ABERTO = "ABERTO"
    RESERVADO = "RESERVADO"
    DEVOLVIDO = "DEVOLVIDO"
    ARQUIVADO = "ARQUIVADO"

class StatusMatch(enum.Enum):
    PENDENTE = "PENDENTE"
    CONFIRMADO = "CONFIRMADO"
    RECUSADO = "RECUSADO"

class StatusRecuperacao(enum.Enum):
    CONFIRMADA = "CONFIRMADA"
    RESERVADA = "RESERVADA"
    RETIRADA = "RETIRADA"
    DEVOLVIDA = "DEVOLVIDA"
    CANCELADA = "CANCELADA"

class OrigemRecompensa(enum.Enum):
    REGRA_PONTOS = "REGRA_PONTOS"
    OFERTA_PROPRIETARIO = "OFERTA_PROPRIETARIO"

class StatusRecompensa(enum.Enum):
    PENDENTE = "PENDENTE"
    RECEBIDA = "RECEBIDA"
    CANCELADA = "CANCELADA"

class TipoNotificacao(enum.Enum):
    MATCH_IDENTIFICADO = "MATCH_IDENTIFICADO"
    RECUPERACAO_ATUALIZADA = "RECUPERACAO_ATUALIZADA"
    ITEM_ATUALIZADO = "ITEM_ATUALIZADO"
    RECOMPENSA = "RECOMPENSA"

class PlataformaDispositivo(enum.Enum):
    WEB = "WEB"
    ANDROID = "ANDROID"
    IOS = "IOS"

def pg_enum(py_enum: type[enum.Enum], name: str) -> Enum:
    """(create_type=False: o schema.sql já o criou)"""
    return Enum(py_enum, name=name, create_type=False)

def _pk() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)

_now = func.now()
# ---------------------------------------------------------------------------
# Acesso e Perfil
# ---------------------------------------------------------------------------
class Usuario(db.Model):
    __tablename__ = "usuario"

    id: Mapped[int] = _pk()
    nome: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(254))
    senha_hash: Mapped[str] = mapped_column(String(255))
    papel: Mapped[PapelUsuario] = mapped_column(
        pg_enum(PapelUsuario, "papel_usuario"),
        default=PapelUsuario.USUARIO, server_default=text("'USUARIO'"))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)

    perfil: Mapped[Optional["Perfil"]] = relationship(
        back_populates="usuario", uselist=False, cascade="all, delete-orphan")
    dispositivos: Mapped[list["DispositivoFcm"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan")
    itens: Mapped[list["Item"]] = relationship(back_populates="usuario")
    notificacoes: Mapped[list["Notificacao"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan")
    recompensas: Mapped[list["Recompensa"]] = relationship(back_populates="beneficiario")

    def __repr__(self) -> str:
        return f"<Usuario {self.id} {self.email}>"

class Perfil(db.Model):
    __tablename__ = "perfil"

    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True)
    telefone: Mapped[Optional[str]] = mapped_column(String(20))
    foto_url: Mapped[Optional[str]] = mapped_column(Text)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)

    usuario: Mapped[Usuario] = relationship(back_populates="perfil")

class DispositivoFcm(db.Model):
    __tablename__ = "dispositivo_fcm"

    id: Mapped[int] = _pk()
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(Text, unique=True)
    plataforma: Mapped[PlataformaDispositivo] = mapped_column(
        pg_enum(PlataformaDispositivo, "plataforma_dispositivo"),
        default=PlataformaDispositivo.WEB, server_default=text("'WEB'"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
    ultimo_uso_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    usuario: Mapped[Usuario] = relationship(back_populates="dispositivos")
# ---------------------------------------------------------------------------
# Postos de Coleta
# ---------------------------------------------------------------------------
class PostoColeta(db.Model):
    __tablename__ = "posto_coleta"

    id: Mapped[int] = _pk()
    nome: Mapped[str] = mapped_column(String(150))
    endereco: Mapped[str] = mapped_column(Text)
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    horario_funcionamento: Mapped[Optional[str]] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)

    operadores: Mapped[list["PostoOperador"]] = relationship(
        back_populates="posto", cascade="all, delete-orphan")
    itens: Mapped[list["Item"]] = relationship(back_populates="posto")

class PostoOperador(db.Model):
    __tablename__ = "posto_operador"

    posto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posto_coleta.id", ondelete="CASCADE"), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True)

    posto: Mapped[PostoColeta] = relationship(back_populates="operadores")
    usuario: Mapped[Usuario] = relationship()
# ---------------------------------------------------------------------------
# Itens
# ---------------------------------------------------------------------------
class Item(db.Model):
    """
    Cada item é registrado como PERDIDO ou ENCONTRADO. A categoria define quais atributos
      ELETRONICO: marca/modelo nas colunas próprias
      DOCUMENTO : atributos = {"tipo_documento": "...", "orgao_emissor": "..."}
      ACESSORIO : atributos = {"material": "..."}
    """
    __tablename__ = "item"

    id: Mapped[int] = _pk()
    usuario_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuario.id"))
    tipo_registro: Mapped[TipoRegistro] = mapped_column(pg_enum(TipoRegistro, "tipo_registro"))
    categoria: Mapped[CategoriaItem] = mapped_column(pg_enum(CategoriaItem, "categoria_item"))
    descricao: Mapped[str] = mapped_column(Text)
    cor: Mapped[Optional[str]] = mapped_column(String(40))
    marca: Mapped[Optional[str]] = mapped_column(String(80))
    modelo: Mapped[Optional[str]] = mapped_column(String(80))
    atributos: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"))
    localizacao: Mapped[Optional[str]] = mapped_column(Text)
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    data_ocorrencia: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    imagem_url: Mapped[Optional[str]] = mapped_column(Text)  # Firebase Storage
    status: Mapped[StatusItem] = mapped_column(
        pg_enum(StatusItem, "status_item"),
        default=StatusItem.ABERTO, server_default=text("'ABERTO'"))
    posto_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("posto_coleta.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)

    # Coluna GERADA pelo banco (nunca é enviada em INSERT/UPDATE). Usada na busca textual:
    #   Item.query.filter(Item.busca.op("@@")(func.plainto_tsquery("portuguese", "celular azul")))
    busca = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('portuguese', coalesce(descricao,'') || ' ' || coalesce(cor,'') || ' ' "
            "|| coalesce(marca,'') || ' ' || coalesce(modelo,''))",
            persisted=True),
        deferred=True)

    usuario: Mapped[Usuario] = relationship(back_populates="itens")
    posto: Mapped[Optional[PostoColeta]] = relationship(back_populates="itens")

    def __repr__(self) -> str:
        return f"<Item {self.id} {self.tipo_registro.name} {self.categoria.name}>"
# ---------------------------------------------------------------------------
# Match e Recuperação
# ---------------------------------------------------------------------------
class Match(db.Model):
    __tablename__ = "match"
    __table_args__ = (
        ForeignKeyConstraint(["item_perdido_id", "tipo_perdido"],
                             ["item.id", "item.tipo_registro"]),
        ForeignKeyConstraint(["item_encontrado_id", "tipo_encontrado"],
                             ["item.id", "item.tipo_registro"]),
    )

    id: Mapped[int] = _pk()
    item_perdido_id: Mapped[int] = mapped_column(BigInteger)
    item_encontrado_id: Mapped[int] = mapped_column(BigInteger)
    tipo_perdido: Mapped[TipoRegistro] = mapped_column(
        pg_enum(TipoRegistro, "tipo_registro"),
        default=TipoRegistro.PERDIDO, server_default=text("'PERDIDO'"))
    tipo_encontrado: Mapped[TipoRegistro] = mapped_column(
        pg_enum(TipoRegistro, "tipo_registro"),
        default=TipoRegistro.ENCONTRADO, server_default=text("'ENCONTRADO'"))
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4))  # 0 a 1
    status: Mapped[StatusMatch] = mapped_column(
        pg_enum(StatusMatch, "status_match"),
        default=StatusMatch.PENDENTE, server_default=text("'PENDENTE'"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
    decidido_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    item_perdido: Mapped[Item] = relationship(
        foreign_keys=[item_perdido_id],
        primaryjoin="Item.id == Match.item_perdido_id", viewonly=True)
    item_encontrado: Mapped[Item] = relationship(
        foreign_keys=[item_encontrado_id],
        primaryjoin="Item.id == Match.item_encontrado_id", viewonly=True)
    recuperacao: Mapped[Optional["Recuperacao"]] = relationship(
        back_populates="match", uselist=False,
        primaryjoin="Match.id == Recuperacao.match_id", foreign_keys="Recuperacao.match_id")

class Recuperacao(db.Model):
    __tablename__ = "recuperacao"
    __table_args__ = (
        ForeignKeyConstraint(["match_id", "item_encontrado_id"],
                             ["match.id", "match.item_encontrado_id"]),
    )

    id: Mapped[int] = _pk()
    match_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    item_encontrado_id: Mapped[int] = mapped_column(BigInteger)
    posto_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("posto_coleta.id"))
    status: Mapped[StatusRecuperacao] = mapped_column(
        pg_enum(StatusRecuperacao, "status_recuperacao"),
        default=StatusRecuperacao.CONFIRMADA, server_default=text("'CONFIRMADA'"))
    confirmada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
    reservada_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    retirada_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    devolvida_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    observacao: Mapped[Optional[str]] = mapped_column(Text)

    match: Mapped[Match] = relationship(
        back_populates="recuperacao",
        primaryjoin="Match.id == Recuperacao.match_id", foreign_keys=[match_id])
    posto: Mapped[Optional[PostoColeta]] = relationship()
    recompensas: Mapped[list["Recompensa"]] = relationship(back_populates="recuperacao")
# ---------------------------------------------------------------------------
# Recompensas, Notificações e Histórico
# ---------------------------------------------------------------------------
class Recompensa(db.Model):
    __tablename__ = "recompensa"

    id: Mapped[int] = _pk()
    beneficiario_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuario.id"))
    recuperacao_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("recuperacao.id"))
    origem: Mapped[OrigemRecompensa] = mapped_column(pg_enum(OrigemRecompensa, "origem_recompensa"))
    pontos: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    descricao: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[StatusRecompensa] = mapped_column(
        pg_enum(StatusRecompensa, "status_recompensa"),
        default=StatusRecompensa.PENDENTE, server_default=text("'PENDENTE'"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
    recebida_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    beneficiario: Mapped[Usuario] = relationship(back_populates="recompensas")
    recuperacao: Mapped[Optional[Recuperacao]] = relationship(back_populates="recompensas")

class Notificacao(db.Model):
    __tablename__ = "notificacao"

    id: Mapped[int] = _pk()
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"))
    tipo: Mapped[TipoNotificacao] = mapped_column(pg_enum(TipoNotificacao, "tipo_notificacao"))
    titulo: Mapped[str] = mapped_column(String(150))
    corpo: Mapped[str] = mapped_column(Text)
    match_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("match.id", ondelete="SET NULL"))
    dados: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    lida: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
    enviada_fcm_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    usuario: Mapped[Usuario] = relationship(back_populates="notificacoes")

class HistoricoEvento(db.Model):
    __tablename__ = "historico_evento"

    id: Mapped[int] = _pk()
    entidade: Mapped[str] = mapped_column(String(30))
    entidade_id: Mapped[int] = mapped_column(BigInteger)
    evento: Mapped[str] = mapped_column(String(60))
    usuario_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"))
    dados: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
# ---------------------------------------------------------------------------
# Operações atômicas implementadas no banco
# ---------------------------------------------------------------------------
def reservar_item(match_id: int, posto_id: Optional[int] = None) -> int:
    return db.session.execute(
        text("SELECT reservar_item(:m, :p)"), {"m": match_id, "p": posto_id}
    ).scalar_one()

def pontuacao_do_usuario(usuario_id: int) -> int:
    return db.session.execute(
        text("SELECT pontos_total FROM pontuacao_usuario WHERE usuario_id = :u"),
        {"u": usuario_id},
    ).scalar_one_or_none() or 0