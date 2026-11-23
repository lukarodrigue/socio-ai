"""Tabelas do Beta.

- Evento: o Segundo Cérebro. Só recebe INSERT (ver brain.py e o gatilho de banco).
- Aprovacao: fila do que o Auditor segurou.
- Titulo / Lancamento: contas a receber e extrato bancário.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def agora() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Evento(Base):
    __tablename__ = "eventos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, index=True)
    agente: Mapped[str] = mapped_column(String(40), index=True)
    tipo: Mapped[str] = mapped_column(String(60), index=True)
    resumo: Mapped[str] = mapped_column(Text)
    dados: Mapped[dict] = mapped_column(JSON, default=dict)
    tarefa_id: Mapped[str | None] = mapped_column(String(40), index=True)
    chave: Mapped[str | None] = mapped_column(String(120), index=True)  # para não registrar a mesma divergência duas vezes


class Aprovacao(Base):
    __tablename__ = "aprovacoes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    agente: Mapped[str] = mapped_column(String(40))
    acao: Mapped[str] = mapped_column(String(60))
    descricao: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)
    valor: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    motivo: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pendente", index=True)  # pendente|aprovada|rejeitada
    decidido_por: Mapped[str | None] = mapped_column(String(80))
    decidido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chave: Mapped[str] = mapped_column(String(120), unique=True)  # evita duplicar o mesmo pedido


class Titulo(Base):
    """Conta a receber (venda a prazo, boleto emitido, cobrança Pix, venda no cartão)."""
    __tablename__ = "titulos"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    cliente: Mapped[str] = mapped_column(String(120))
    documento: Mapped[str | None] = mapped_column(String(20))
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    vencimento: Mapped[date] = mapped_column(Date, index=True)
    meio: Mapped[str] = mapped_column(String(10))  # pix|boleto|cartao
    referencia: Mapped[str | None] = mapped_column(String(60), index=True)  # txid | nosso número | NSU
    status: Mapped[str] = mapped_column(String(20), default="aberto", index=True)  # aberto|baixado
    lancamento_id: Mapped[str | None] = mapped_column(ForeignKey("lancamentos.id"))


class Lancamento(Base):
    """Crédito no extrato bancário ou na liquidação da maquininha."""
    __tablename__ = "lancamentos"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    data: Mapped[date] = mapped_column(Date, index=True)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    meio: Mapped[str] = mapped_column(String(10))
    descricao: Mapped[str] = mapped_column(String(200), default="")
    pagador_nome: Mapped[str | None] = mapped_column(String(120))
    pagador_documento: Mapped[str | None] = mapped_column(String(20))
    referencia: Mapped[str | None] = mapped_column(String(60), index=True)
    conciliado: Mapped[bool] = mapped_column(default=False, index=True)
