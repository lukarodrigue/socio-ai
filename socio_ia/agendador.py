"""Gatilhos por horário, lidos da agenda do Playbook."""
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from .agentes import dono, financeiro
from .app import Contexto


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def iniciar(ctx: Contexto) -> BackgroundScheduler:
    pb = ctx.auditor.playbook
    tz = ZoneInfo(pb.empresa.fuso)
    sched = BackgroundScheduler(timezone=tz)

    def rodar(fn):
        def job():
            with ctx.Sessao() as s:
                fn(s)
                s.commit()
        return job

    hoje = lambda: datetime.now(tz).date()  # noqa: E731
    for i, horario in enumerate(pb.agenda.financeiro_conciliacao):
        h, m = _hm(horario)
        sched.add_job(rodar(lambda s, hr=horario: financeiro.executar_conciliacao(s, ctx.auditor, hoje(), f"agenda {hr}")),
                      "cron", hour=h, minute=m, id=f"financeiro_{i}")
    h, m = _hm(pb.agenda.dono_inicio_dia)
    sched.add_job(rodar(lambda s: dono.inicio_do_dia(s, ctx.auditor)), "cron", hour=h, minute=m, id="dono_inicio")
    h, m = _hm(pb.agenda.dono_relatorio)
    sched.add_job(rodar(lambda s: dono.relatorio_do_dia(s, ctx.auditor, hoje(), ctx.settings.ollama_url,
                                                        ctx.settings.ollama_model)),
                  "cron", hour=h, minute=m, id="dono_relatorio")
    sched.start()
    return sched
