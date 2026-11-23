"""Entrada de dados no Beta: CSV padronizado e OFX (formato que todo banco exporta).

Integração direta com API de banco/adquirente fica para depois do piloto: cada banco
tem a sua, exige credenciamento, e o cliente-piloto vai definir qual vale a pena.
"""
import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from .models import Lancamento, Titulo

COLS_TITULOS = ["id", "cliente", "documento", "valor", "vencimento", "meio", "referencia"]
COLS_EXTRATO = ["id", "data", "valor", "meio", "descricao", "pagador_nome", "pagador_documento", "referencia"]
MEIOS = {"pix", "boleto", "cartao", "outro"}


class ErroImportacao(ValueError):
    pass


def _dec(v: str, linha: int) -> Decimal:
    s = v.strip().replace("R$", "").replace(" ", "")
    if "," in s:  # formato brasileiro: 1.234,56
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation as e:
        raise ErroImportacao(f"linha {linha}: valor inválido '{v}'") from e


def _data(v: str, linha: int) -> date:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(v.strip(), fmt).date()
        except ValueError:
            pass
    raise ErroImportacao(f"linha {linha}: data inválida '{v}'")


def _ler_csv(conteudo: str, obrigatorias: list[str]) -> list[dict]:
    leitor = csv.DictReader(io.StringIO(conteudo))
    faltando = set(obrigatorias) - set(leitor.fieldnames or [])
    if faltando:
        raise ErroImportacao(f"colunas faltando: {', '.join(sorted(faltando))}")
    return list(leitor)


def importar_titulos_csv(sessao: Session, conteudo: str) -> tuple[int, int]:
    novos = existentes = 0
    for i, r in enumerate(_ler_csv(conteudo, COLS_TITULOS), start=2):
        if r["meio"] not in MEIOS:
            raise ErroImportacao(f"linha {i}: meio '{r['meio']}' inválido")
        if sessao.get(Titulo, r["id"]):
            existentes += 1
            continue
        sessao.add(Titulo(id=r["id"], cliente=r["cliente"], documento=r["documento"] or None,
                          valor=_dec(r["valor"], i), vencimento=_data(r["vencimento"], i),
                          meio=r["meio"], referencia=r["referencia"] or None))
        novos += 1
    sessao.flush()
    return novos, existentes


def importar_extrato_csv(sessao: Session, conteudo: str) -> tuple[int, int]:
    novos = existentes = 0
    for i, r in enumerate(_ler_csv(conteudo, COLS_EXTRATO), start=2):
        valor = _dec(r["valor"], i)
        if valor <= 0:
            continue  # Beta concilia só recebimentos
        if sessao.get(Lancamento, r["id"]):
            existentes += 1
            continue
        sessao.add(Lancamento(id=r["id"], data=_data(r["data"], i), valor=valor,
                              meio=r["meio"] if r["meio"] in MEIOS else "outro", descricao=r["descricao"],
                              pagador_nome=r["pagador_nome"] or None, pagador_documento=r["pagador_documento"] or None,
                              referencia=r["referencia"] or None))
        novos += 1
    sessao.flush()
    return novos, existentes


def _ofx_tag(bloco: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>([^<\r\n]*)", bloco, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _meio_por_texto(texto: str) -> str:
    t = texto.upper()
    if "PIX" in t:
        return "pix"
    if any(k in t for k in ("BOLETO", "COBRANCA", "COBRANÇA", "LIQUIDACAO", "LIQUIDAÇÃO")):
        return "boleto"
    if any(k in t for k in ("CIELO", "REDE", "STONE", "GETNET", "PAGSEGURO", "CARTAO", "CARTÃO")):
        return "cartao"
    return "outro"


def importar_extrato_ofx(sessao: Session, conteudo: str, prefixo_id: str = "ofx") -> tuple[int, int]:
    """Lê os créditos de um OFX (SGML ou XML). OFX normalmente não traz CPF/CNPJ do pagador,
    então esses lançamentos caem nas regras 1 (se o MEMO tiver o txid) ou 3 (nome)."""
    novos = existentes = 0
    for bloco in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", conteudo, re.IGNORECASE | re.DOTALL):
        valor_txt = _ofx_tag(bloco, "TRNAMT")
        fitid = _ofx_tag(bloco, "FITID")
        dt = _ofx_tag(bloco, "DTPOSTED")
        if not (valor_txt and fitid and dt):
            continue
        valor = Decimal(valor_txt.replace(",", "."))
        if valor <= 0:
            continue
        lid = f"{prefixo_id}-{fitid}"
        if sessao.get(Lancamento, lid):
            existentes += 1
            continue
        memo = _ofx_tag(bloco, "MEMO") or ""
        nome = _ofx_tag(bloco, "NAME")
        txid = re.search(r"\b([A-Za-z0-9]{26,35})\b", memo)
        sessao.add(Lancamento(id=lid, data=datetime.strptime(dt[:8], "%Y%m%d").date(), valor=valor,
                              meio=_meio_por_texto(f"{memo} {nome or ''}"), descricao=memo[:200],
                              pagador_nome=nome, referencia=txid.group(1) if txid else None))
        novos += 1
    sessao.flush()
    return novos, existentes
