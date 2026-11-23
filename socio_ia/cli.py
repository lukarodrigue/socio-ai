"""Linha de comando do Beta.

  socio-ia demo                      # tudo em memória: gera empresa fictícia, concilia e mostra o relatório
  socio-ia gerar-ficticia dados/     # só gera os CSVs + gabarito
  socio-ia importar --titulos dados/titulos.csv --extrato dados/extrato.csv
  socio-ia conciliar [--data 2026-11-20]
  socio-ia aprovacoes
  socio-ia aprovar 12 --por gestor
  socio-ia relatorio [--dia 2026-11-23]
"""
import argparse
import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select


def _hoje(ctx) -> date:
    return datetime.now(ZoneInfo(ctx.auditor.playbook.empresa.fuso)).date()


def main(argv=None):
    p = argparse.ArgumentParser(prog="socio-ia")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo")
    g = sub.add_parser("gerar-ficticia"); g.add_argument("pasta")
    i = sub.add_parser("importar"); i.add_argument("--titulos"); i.add_argument("--extrato")
    c = sub.add_parser("conciliar"); c.add_argument("--data", type=date.fromisoformat)
    sub.add_parser("aprovacoes")
    a = sub.add_parser("aprovar"); a.add_argument("id", type=int); a.add_argument("--por", required=True)
    r = sub.add_parser("rejeitar"); r.add_argument("id", type=int); r.add_argument("--por", required=True)
    rel = sub.add_parser("relatorio"); rel.add_argument("--dia", type=date.fromisoformat)
    args = p.parse_args(argv)

    from . import ficticia
    if args.cmd == "gerar-ficticia":
        print(json.dumps(ficticia.salvar(args.pasta), ensure_ascii=False))
        return
    if args.cmd == "demo":
        import os
        os.environ.setdefault("SOCIO_DATABASE_URL", "sqlite://")
        pasta = Path(tempfile.mkdtemp())
        ficticia.salvar(pasta)
        gab = json.loads((pasta / "gabarito.json").read_text(encoding="utf-8"))
        main(["importar", "--titulos", str(pasta / "titulos.csv"), "--extrato", str(pasta / "extrato.csv")])
        main(["conciliar", "--data", gab["data_ref"]])
        main(["relatorio"])
        return

    from .agentes import dono, financeiro
    from .app import contexto
    from .importadores import importar_extrato_csv, importar_extrato_ofx, importar_titulos_csv
    from .models import Aprovacao
    from .pipeline import ErroAprovacao, decidir_aprovacao

    ctx = contexto()
    with ctx.Sessao() as s:
        if args.cmd == "importar":
            if args.titulos:
                print("títulos (novos, já existiam):", importar_titulos_csv(s, Path(args.titulos).read_text(encoding="utf-8-sig")))
            if args.extrato:
                txt = Path(args.extrato).read_text(encoding="utf-8-sig", errors="replace")
                fn = importar_extrato_ofx if args.extrato.lower().endswith(".ofx") else importar_extrato_csv
                print("extrato (novos, já existiam):", fn(s, txt))
        elif args.cmd == "conciliar":
            res = financeiro.executar_conciliacao(s, ctx.auditor, args.data or _hoje(ctx), "linha de comando")
            print(f"executadas={res.executadas} aprovacoes={res.aprovacoes_criadas} sugestoes={res.sugestoes} "
                  f"bloqueadas={res.bloqueadas} ignoradas={res.ignoradas} erros={len(res.erros)}")
        elif args.cmd == "aprovacoes":
            for ap in s.scalars(select(Aprovacao).where(Aprovacao.status == "pendente").order_by(Aprovacao.id)):
                print(f"#{ap.id:<5} {ap.descricao}\n       motivo: {ap.motivo}")
        elif args.cmd in ("aprovar", "rejeitar"):
            try:
                ap = decidir_aprovacao(s, ctx.auditor, args.id, args.por, args.cmd == "aprovar")
                print(f"#{ap.id} {ap.status}")
            except ErroAprovacao as e:
                raise SystemExit(f"erro: {e}")
        elif args.cmd == "relatorio":
            print(dono.relatorio_do_dia(s, ctx.auditor, args.dia or _hoje(ctx),
                                        ctx.settings.ollama_url, ctx.settings.ollama_model)["markdown"])
        s.commit()


if __name__ == "__main__":
    main()
