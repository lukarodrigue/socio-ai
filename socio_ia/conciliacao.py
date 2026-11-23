"""Motor de conciliação — 100% determinístico, sem IA.

Dinheiro não pode depender de um modelo de linguagem "achar" que dois registros batem.
Aqui as regras são explícitas, testáveis e reproduzíveis: a mesma entrada sempre dá
a mesma saída.

Ordem das regras (da mais forte para a mais fraca):
  1. Referência (txid do Pix, nosso número do boleto, NSU do cartão)
  2. CPF/CNPJ do pagador + valor + janela de datas
  3. Valor + janela de datas + nome parecido  → confiança baixa, sempre vai para aprovação
"""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher

from .playbook import Financeiro

CENT = Decimal("0.01")


@dataclass(frozen=True)
class TituloIn:
    id: str
    cliente: str
    documento: str | None
    valor: Decimal
    vencimento: date
    meio: str
    referencia: str | None
    status: str = "aberto"


@dataclass(frozen=True)
class LancamentoIn:
    id: str
    data: date
    valor: Decimal
    meio: str
    pagador_nome: str | None = None
    pagador_documento: str | None = None
    referencia: str | None = None


@dataclass
class Match:
    titulo: TituloIn
    lancamento: LancamentoIn
    regra: str
    confianca: str  # "alta" | "baixa"


@dataclass
class Divergencia:
    tipo: str  # pagamento_duplicado | valor_divergente | credito_nao_identificado | titulo_em_atraso | taxa_cartao_acima
    descricao: str
    titulo_id: str | None = None
    lancamento_id: str | None = None
    valor: Decimal | None = None


@dataclass
class ResultadoConciliacao:
    matches: list[Match] = field(default_factory=list)
    divergencias: list[Divergencia] = field(default_factory=list)


def normalizar_nome(nome: str | None) -> str:
    if not nome:
        return ""
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(ltda|me|epp|eireli|s a|sa|cia|comercio|de|da|do|e)\b", " ", s)
    return " ".join(s.split())


def so_digitos(doc: str | None) -> str:
    return re.sub(r"\D", "", doc or "")


def similaridade(a: str | None, b: str | None) -> float:
    na, nb = normalizar_nome(a), normalizar_nome(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def liquido_cartao(bruto: Decimal, taxa: float) -> Decimal:
    return (bruto * (Decimal(1) - Decimal(str(taxa)))).quantize(CENT, ROUND_HALF_UP)


def brl(v: Decimal) -> str:
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def conciliar(
    titulos: list[TituloIn],
    lancamentos: list[LancamentoIn],
    cfg: Financeiro,
    data_ref: date,
    dias_carencia_atraso: int = 3,
) -> ResultadoConciliacao:
    res = ResultadoConciliacao()
    tol = Decimal(str(cfg.tolerancia_centavos))
    antes = timedelta(days=cfg.janela_dias_antes_vencimento)
    depois = timedelta(days=cfg.janela_dias_depois_vencimento)

    por_ref = {t.referencia: t for t in titulos if t.referencia}
    usados: set[str] = set()          # títulos já ligados a um lançamento nesta rodada
    com_divergencia: set[str] = set()  # títulos que já geraram divergência de valor
    pendentes: list[LancamentoIn] = []

    def na_janela(t: TituloIn, l: LancamentoIn) -> bool:
        return t.vencimento - antes <= l.data <= t.vencimento + depois

    # ---------- Regra 1: referência
    for l in sorted(lancamentos, key=lambda x: (x.data, x.id)):
        t = por_ref.get(l.referencia) if l.referencia else None
        if t is None:
            pendentes.append(l)
            continue
        if t.status != "aberto" or t.id in usados:
            res.divergencias.append(Divergencia(
                "pagamento_duplicado",
                f"{brl(l.valor)} de {l.pagador_nome or 'pagador não informado'} em {l.data:%d/%m} "
                f"refere-se ao título {t.id}, que já foi pago",
                t.id, l.id, l.valor))
            continue
        if t.meio == "cartao":
            esperado = liquido_cartao(t.valor, cfg.taxa_cartao_contratada)
            taxa_real = (Decimal(1) - l.valor / t.valor) if t.valor else Decimal(0)
            limite_taxa = Decimal(str(cfg.taxa_cartao_contratada + cfg.tolerancia_taxa_cartao))
            res.matches.append(Match(t, l, "referencia", "alta"))
            usados.add(t.id)
            if taxa_real > limite_taxa:
                res.divergencias.append(Divergencia(
                    "taxa_cartao_acima",
                    f"Liquidação NSU {t.referencia}: taxa cobrada {taxa_real * 100:.2f}% "
                    f"(contratada {cfg.taxa_cartao_contratada * 100:.2f}%). "
                    f"Esperado {brl(esperado)}, recebido {brl(l.valor)}",
                    t.id, l.id, (esperado - l.valor)))
            continue
        if abs(l.valor - t.valor) <= tol:
            res.matches.append(Match(t, l, "referencia", "alta"))
            usados.add(t.id)
        else:
            usados.add(t.id)
            com_divergencia.add(t.id)
            res.divergencias.append(Divergencia(
                "valor_divergente",
                f"Título {t.id} ({t.cliente}) de {brl(t.valor)} recebeu {brl(l.valor)} "
                f"(diferença {brl(t.valor - l.valor)})",
                t.id, l.id, t.valor - l.valor))

    abertos = [t for t in titulos if t.status == "aberto" and t.meio != "cartao"]

    # ---------- Regra 2: documento + valor + janela
    sobra: list[LancamentoIn] = []
    for l in pendentes:
        doc = so_digitos(l.pagador_documento)
        if not doc:
            sobra.append(l)
            continue
        do_cliente = [t for t in abertos if t.id not in usados and so_digitos(t.documento) == doc]
        cand = [t for t in do_cliente if abs(t.valor - l.valor) <= tol and na_janela(t, l)]
        if cand:
            cand.sort(key=lambda t: (abs((t.vencimento - l.data).days), t.vencimento))
            t = cand[0]
            res.matches.append(Match(t, l, "documento+valor", "alta" if len(cand) == 1 else "baixa"))
            usados.add(t.id)
        else:
            sobra.append(l)

    # ---------- Regra 3: valor + janela + nome parecido
    for l in sobra:
        cand = [t for t in abertos if t.id not in usados and abs(t.valor - l.valor) <= tol and na_janela(t, l)
                and similaridade(t.cliente, l.pagador_nome) >= cfg.similaridade_nome_minima]
        if len(cand) == 1:
            res.matches.append(Match(cand[0], l, "valor+nome", "baixa"))
            usados.add(cand[0].id)
        else:
            motivo = "nenhum título compatível" if not cand else f"{len(cand)} títulos compatíveis, ambíguo"
            res.divergencias.append(Divergencia(
                "credito_nao_identificado",
                f"Crédito de {brl(l.valor)} em {l.data:%d/%m} de {l.pagador_nome or 'pagador não informado'} "
                f"({l.meio}) sem título correspondente: {motivo}",
                None, l.id, l.valor))

    # ---------- Títulos em atraso
    corte = data_ref - timedelta(days=dias_carencia_atraso)
    for t in titulos:
        if t.status == "aberto" and t.id not in usados and t.id not in com_divergencia and t.vencimento < corte:
            dias = (data_ref - t.vencimento).days
            res.divergencias.append(Divergencia(
                "titulo_em_atraso",
                f"{t.cliente}: título {t.id} de {brl(t.valor)} venceu em {t.vencimento:%d/%m/%Y} ({dias} dias)",
                t.id, None, t.valor))
    return res
