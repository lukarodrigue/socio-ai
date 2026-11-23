"""Segundo Cérebro (Beta): registro cronológico e imutável de tudo o que acontece.

No Beta ele é um log de eventos consultável por data, agente e tipo.
A busca por significado (pgvector sobre documentos da empresa) entra na próxima etapa.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Evento


def registrar(
    sessao: Session,
    agente: str,
    tipo: str,
    resumo: str,
    dados: dict | None = None,
    tarefa_id: str | None = None,
    chave: str | None = None,
) -> Evento:
    ev = Evento(agente=agente, tipo=tipo, resumo=resumo, dados=dados or {}, tarefa_id=tarefa_id, chave=chave)
    sessao.add(ev)
    sessao.flush()
    return ev


def ja_registrado(sessao: Session, chave: str) -> bool:
    return sessao.scalar(select(Evento.id).where(Evento.chave == chave).limit(1)) is not None


def consultar(
    sessao: Session,
    desde: datetime | None = None,
    ate: datetime | None = None,
    agente: str | None = None,
    tipo: str | None = None,
    limite: int = 500,
) -> list[Evento]:
    q = select(Evento)
    if desde:
        q = q.where(Evento.criado_em >= desde)
    if ate:
        q = q.where(Evento.criado_em < ate)
    if agente:
        q = q.where(Evento.agente == agente)
    if tipo:
        q = q.where(Evento.tipo == tipo)
    return list(sessao.scalars(q.order_by(Evento.id).limit(limite)))
