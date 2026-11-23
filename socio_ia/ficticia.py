"""Empresa fictícia: Padaria Pão Dourado Ltda — 12 meses de dados com erros plantados.

Serve para duas coisas:
  1. Teste automático: o sistema precisa encontrar 100% dos erros plantados e nenhum a mais.
  2. Demonstração para cliente, sem expor dado real de ninguém.

Tudo é determinístico (semente fixa): rodar de novo gera exatamente os mesmos dados.
"""
import csv
import json
import random
import string
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

CENT = Decimal("0.01")

NOMES_CLIENTES = [
    "Restaurante Sabor do Cerrado", "Lanchonete Ponto Certo", "Café Ipê Amarelo", "Hotel Fronteira Sul",
    "Mercado Bom Preço", "Pizzaria Forno a Lenha", "Buffet Doce Festa", "Conveniência Posto Avenida",
    "Cantina Universitária Dourados", "Hamburgueria Brasa", "Empório Grão Fino", "Restaurante Tempero Caseiro",
    "Café Colonial Serra", "Lanchonete Estação", "Mercearia Dona Rosa", "Pastelaria Feira Livre",
    "Hospital São Lucas Refeitório", "Escola Pequeno Príncipe Cantina", "Bar do Tião", "Cafeteria Aroma",
    "Restaurante Pantanal Grill", "Supermercado Vila Nova", "Doceria Mel e Canela", "Pousada Rio Brilhante",
    "Lanchonete Sabor Mineiro", "Churrascaria Gaúcha", "Padaria Parceira Centro", "Food Truck Rota 163",
]
PAGADORES_DESCONHECIDOS = ["JOAO P SILVA", "MARIA APARECIDA SOUZA", "TRANSPORTES RAPIDO MS", "CLINICA BEM ESTAR"]


@dataclass
class TituloRow:
    id: str
    cliente: str
    documento: str
    valor: str
    vencimento: str
    meio: str
    referencia: str


@dataclass
class LancRow:
    id: str
    data: str
    valor: str
    meio: str
    descricao: str
    pagador_nome: str
    pagador_documento: str
    referencia: str


def _cnpj(rng: random.Random) -> str:
    d = [rng.randint(0, 9) for _ in range(12)]
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        s = sum(a * b for a, b in zip(d, pesos)) % 11
        d.append(0 if s < 2 else 11 - s)
    n = "".join(map(str, d))
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"


def _nome_no_banco(nome: str) -> str:
    """Bancos mostram o nome em maiúsculas, sem acento e às vezes cortado."""
    import unicodedata
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().upper()
    return s[:28]


def gerar(data_fim: date = date(2026, 11, 20), seed: int = 42, taxa_cartao: float = 0.0299, carencia: int = 3):
    rng = random.Random(seed)
    inicio = data_fim - timedelta(days=365)
    clientes = [(f"{n} Ltda", _cnpj(rng)) for n in NOMES_CLIENTES]

    titulos: dict[str, TituloRow] = {}
    lancs: dict[str, LancRow] = {}
    pagamento_de: dict[str, str] = {}     # titulo_id -> lancamento_id (pagamentos legítimos)
    tipo_pagamento: dict[str, str] = {}   # titulo_id -> "ref" | "doc" | "nome"
    seq = {"t": 0, "l": 0}

    def novo_tid(prefixo="T"):
        seq["t"] += 1
        return f"{prefixo}{seq['t']:05d}"

    def novo_lid():
        seq["l"] += 1
        return f"L{seq['l']:06d}"

    def ref_para(meio):
        if meio == "pix":
            return "".join(rng.choices(string.ascii_uppercase + string.digits, k=32))
        return "".join(rng.choices(string.digits, k=11))

    def pagar(t: TituloRow, cliente: str, doc: str, dia: date, valor: Decimal, modo: str) -> str:
        lid = novo_lid()
        ref = t.referencia if modo == "ref" else ""
        lancs[lid] = LancRow(lid, dia.isoformat(), str(valor), t.meio,
                             f"{'PIX RECEBIDO' if t.meio == 'pix' else 'LIQUIDACAO BOLETO'} {_nome_no_banco(cliente)}",
                             _nome_no_banco(cliente), doc if modo in ("ref", "doc") else "", ref)
        return lid

    # ---------- vendas a prazo para clientes (Pix e boleto)
    for nome, doc in clientes:
        dia = inicio + timedelta(days=rng.randint(0, 6))
        while dia <= data_fim + timedelta(days=10):
            meio = "pix" if rng.random() < 0.55 else "boleto"
            valor = Decimal(rng.randint(18000, 240000)) / 100
            tid = novo_tid()
            t = TituloRow(tid, nome, doc, str(valor), dia.isoformat(), meio, ref_para(meio))
            titulos[tid] = t
            pago_em = dia + timedelta(days=rng.randint(-3, 6))
            if dia <= data_fim - timedelta(days=carencia):
                pago_em = min(pago_em, data_fim)
            if pago_em <= data_fim:
                if meio == "boleto":
                    modo = "ref"
                else:
                    x = rng.random()
                    modo = "ref" if x < 0.80 else ("doc" if x < 0.90 else "nome")
                pagamento_de[tid] = pagar(t, nome, doc, pago_em, valor, modo)
                tipo_pagamento[tid] = modo
            dia += timedelta(days=rng.randint(5, 12))

    # ---------- vendas no cartão: um lote por dia, liquidado em D+30 com desconto da taxa
    dia = inicio
    while dia <= data_fim:
        bruto = Decimal(rng.randint(40000, 250000)) / 100
        tid = f"CART-{dia:%Y%m%d}"
        venc = dia + timedelta(days=30)
        t = TituloRow(tid, "Vendas no cartão (adquirente)", "", str(bruto), venc.isoformat(), "cartao", f"NSU{dia:%Y%m%d}")
        titulos[tid] = t
        if venc <= data_fim:
            liquido = (bruto * (Decimal(1) - Decimal(str(taxa_cartao)))).quantize(CENT, ROUND_HALF_UP)
            lid = novo_lid()
            lancs[lid] = LancRow(lid, venc.isoformat(), str(liquido), "cartao", "CIELO LIQUIDACAO", "CIELO SA", "", t.referencia)
            pagamento_de[tid] = lid
            tipo_pagamento[tid] = "ref"
        dia += timedelta(days=1)

    # ---------- erros plantados
    gabarito = {"divergencias": [], "aprovacao_por_limite": [], "pagamentos_legitimos": {}}
    usados: set[str] = set()
    recentes = [tid for tid, t in titulos.items()
                if not tid.startswith("CART") and tid in pagamento_de and tipo_pagamento[tid] == "ref"
                and data_fim - timedelta(days=90) <= date.fromisoformat(lancs[pagamento_de[tid]].data) <= data_fim - timedelta(days=2)]
    rng.shuffle(recentes)

    def pega(lista):
        while lista:
            tid = lista.pop()
            if tid not in usados:
                usados.add(tid)
                return tid
        raise RuntimeError("faltaram títulos para plantar erros")

    for _ in range(3):  # pagamento em duplicidade
        tid = pega(recentes)
        orig = lancs[pagamento_de[tid]]
        lid = novo_lid()
        lancs[lid] = LancRow(lid, (date.fromisoformat(orig.data) + timedelta(days=1)).isoformat(), orig.valor, orig.meio,
                             orig.descricao, orig.pagador_nome, orig.pagador_documento, orig.referencia)
        gabarito["divergencias"].append({"tipo": "pagamento_duplicado", "titulo_id": tid, "lancamento_id": lid})

    for _ in range(3):  # pagou valor diferente
        tid = pega(recentes)
        lid = pagamento_de.pop(tid)
        menos = Decimal(rng.randint(1000, 8000)) / 100
        lancs[lid].valor = str(Decimal(lancs[lid].valor) - menos)
        gabarito["divergencias"].append({"tipo": "valor_divergente", "titulo_id": tid, "lancamento_id": lid})

    for i in range(3):  # crédito que não corresponde a nenhum título
        lid = novo_lid()
        d = data_fim - timedelta(days=rng.randint(3, 40))
        nome = PAGADORES_DESCONHECIDOS[i]
        lancs[lid] = LancRow(lid, d.isoformat(), str(Decimal(rng.randint(5000, 90000)) / 100), "pix",
                             f"PIX RECEBIDO {nome}", nome, "", "")
        gabarito["divergencias"].append({"tipo": "credito_nao_identificado", "titulo_id": None, "lancamento_id": lid})

    atrasaveis = [tid for tid in recentes if tid not in usados
                  and data_fim - timedelta(days=60) <= date.fromisoformat(titulos[tid].vencimento) <= data_fim - timedelta(days=10)]
    for _ in range(4):  # cliente não pagou
        tid = pega(atrasaveis)
        del lancs[pagamento_de.pop(tid)]
        gabarito["divergencias"].append({"tipo": "titulo_em_atraso", "titulo_id": tid, "lancamento_id": None})

    for valor in (Decimal("7800.00"), Decimal("6350.40")):  # pagamento correto, mas acima do limite de baixa automática
        nome, doc = clientes[rng.randrange(len(clientes))]
        venc = data_fim - timedelta(days=rng.randint(8, 20))
        tid = novo_tid("G")
        t = TituloRow(tid, nome, doc, str(valor), venc.isoformat(), "boleto", ref_para("boleto"))
        titulos[tid] = t
        pagamento_de[tid] = pagar(t, nome, doc, venc, valor, "ref")
        gabarito["aprovacao_por_limite"].append(tid)

    cartoes = [tid for tid in titulos if tid.startswith("CART") and tid in pagamento_de
               and date.fromisoformat(lancs[pagamento_de[tid]].data) >= data_fim - timedelta(days=60)]
    rng.shuffle(cartoes)
    for _ in range(2):  # adquirente cobrou taxa maior que a contratada
        tid = pega(cartoes)
        lid = pagamento_de[tid]
        lancs[lid].valor = str((Decimal(titulos[tid].valor) * Decimal("0.955")).quantize(CENT, ROUND_HALF_UP))
        gabarito["divergencias"].append({"tipo": "taxa_cartao_acima", "titulo_id": tid, "lancamento_id": lid})

    gabarito["pagamentos_legitimos"] = {lid: tid for tid, lid in pagamento_de.items()}
    gabarito["data_ref"] = data_fim.isoformat()
    return list(titulos.values()), sorted(lancs.values(), key=lambda l: (l.data, l.id)), gabarito


def salvar(pasta: str | Path, **kwargs) -> dict:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    titulos, lancs, gabarito = gerar(**kwargs)
    for nome, linhas, cls in (("titulos.csv", titulos, TituloRow), ("extrato.csv", lancs, LancRow)):
        with open(pasta / nome, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(cls.__dataclass_fields__))
            w.writeheader()
            w.writerows(asdict(x) for x in linhas)
    (pasta / "gabarito.json").write_text(json.dumps(gabarito, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"titulos": len(titulos), "lancamentos": len(lancs), "erros_plantados": len(gabarito["divergencias"])}
