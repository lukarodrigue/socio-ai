"""API do Beta. A tela no Beta é o /docs (Swagger) — as telas em React vêm depois do piloto."""
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select

from . import __version__, brain
from .agentes import dono, financeiro
from .app import contexto
from .importadores import ErroImportacao, importar_extrato_csv, importar_extrato_ofx, importar_titulos_csv
from .models import Aprovacao
from .pipeline import ErroAprovacao, decidir_aprovacao


@asynccontextmanager
async def ciclo(app: FastAPI):
    sched = None
    if os.getenv("SOCIO_AGENDADOR", "1") == "1":
        from .agendador import iniciar
        sched = iniciar(contexto())
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="Sócio IA", version=__version__, lifespan=ciclo)


def autenticar(authorization: str | None = Header(default=None)):
    """Beta: um token único por instalação. Antes do primeiro cliente real: login por usuário."""
    token = os.getenv("SOCIO_API_TOKEN")
    if token and not (authorization and secrets.compare_digest(authorization, f"Bearer {token}")):
        raise HTTPException(401, "token inválido")


def sessao():
    with contexto().Sessao() as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise


def hoje() -> date:
    return datetime.now(ZoneInfo(contexto().auditor.playbook.empresa.fuso)).date()


class Decisao(BaseModel):
    aprovador: str
    observacao: str = ""


@app.get("/saude")
def saude():
    return {"ok": True, "versao": __version__, "empresa": contexto().auditor.playbook.empresa.nome}


@app.post("/importar/titulos", dependencies=[Depends(autenticar)])
async def importar_titulos(arquivo: UploadFile = File(...), s=Depends(sessao)):
    try:
        novos, existentes = importar_titulos_csv(s, (await arquivo.read()).decode("utf-8-sig"))
    except ErroImportacao as e:
        raise HTTPException(422, str(e))
    brain.registrar(s, "sistema", "importacao", f"Títulos: {novos} novos, {existentes} já existiam", {"arquivo": arquivo.filename})
    return {"novos": novos, "ja_existiam": existentes}


@app.post("/importar/extrato", dependencies=[Depends(autenticar)])
async def importar_extrato(arquivo: UploadFile = File(...), s=Depends(sessao)):
    texto = (await arquivo.read()).decode("utf-8-sig", errors="replace")
    try:
        if (arquivo.filename or "").lower().endswith(".ofx") or "<OFX>" in texto.upper():
            novos, existentes = importar_extrato_ofx(s, texto)
        else:
            novos, existentes = importar_extrato_csv(s, texto)
    except ErroImportacao as e:
        raise HTTPException(422, str(e))
    brain.registrar(s, "sistema", "importacao", f"Extrato: {novos} novos, {existentes} já existiam", {"arquivo": arquivo.filename})
    return {"novos": novos, "ja_existiam": existentes}


@app.post("/financeiro/conciliar", dependencies=[Depends(autenticar)])
def conciliar(data_ref: date | None = None, s=Depends(sessao)):
    r = financeiro.executar_conciliacao(s, contexto().auditor, data_ref or hoje(), gatilho="pedido na tela")
    return r.__dict__


@app.get("/aprovacoes", dependencies=[Depends(autenticar)])
def listar_aprovacoes(status: str = "pendente", s=Depends(sessao)):
    return [{"id": a.id, "agente": a.agente, "acao": a.acao, "descricao": a.descricao, "valor": a.valor,
             "motivo": a.motivo, "status": a.status, "decidido_por": a.decidido_por}
            for a in s.scalars(select(Aprovacao).where(Aprovacao.status == status).order_by(Aprovacao.id))]


@app.post("/aprovacoes/{aprovacao_id}/aprovar", dependencies=[Depends(autenticar)])
def aprovar(aprovacao_id: int, d: Decisao, s=Depends(sessao)):
    try:
        ap = decidir_aprovacao(s, contexto().auditor, aprovacao_id, d.aprovador, True, d.observacao)
    except ErroAprovacao as e:
        raise HTTPException(409, str(e))
    return {"id": ap.id, "status": ap.status}


@app.post("/aprovacoes/{aprovacao_id}/rejeitar", dependencies=[Depends(autenticar)])
def rejeitar(aprovacao_id: int, d: Decisao, s=Depends(sessao)):
    try:
        ap = decidir_aprovacao(s, contexto().auditor, aprovacao_id, d.aprovador, False, d.observacao)
    except ErroAprovacao as e:
        raise HTTPException(409, str(e))
    return {"id": ap.id, "status": ap.status}


@app.get("/relatorio", response_class=PlainTextResponse, dependencies=[Depends(autenticar)])
def relatorio(dia: date | None = None, s=Depends(sessao)):
    ctx = contexto()
    return dono.montar_relatorio(s, ctx.auditor, dia or hoje(), ctx.settings.ollama_url, ctx.settings.ollama_model)["markdown"]


@app.get("/eventos", dependencies=[Depends(autenticar)])
def eventos(agente: str | None = None, tipo: str | None = None, limite: int = 100, s=Depends(sessao)):
    evs = brain.consultar(s, agente=agente, tipo=tipo, limite=10_000)[-limite:]
    return [{"id": e.id, "quando": e.criado_em, "agente": e.agente, "tipo": e.tipo, "resumo": e.resumo} for e in evs]
