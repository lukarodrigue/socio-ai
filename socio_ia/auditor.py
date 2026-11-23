"""Auditor: decide se uma ação é bloqueada, sugerida, vai para aprovação ou é executada.

Princípio: as regras invioláveis estão AQUI, em código. O Playbook pode reduzir a
autonomia de qualquer ação, mas nunca subir acima do teto definido neste arquivo,
e o agente que propõe a ação também só pode pedir MENOS autonomia, nunca mais.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, IntEnum

from .playbook import Playbook


def brl(v: Decimal) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Nivel(IntEnum):
    PROIBIDO = 0
    SUGERE = 1
    APROVA = 2
    FAZ_E_AVISA = 3
    AUTONOMO = 4


class Decisao(str, Enum):
    BLOQUEAR = "bloquear"
    SUGERIR = "sugerir"
    PEDIR_APROVACAO = "pedir_aprovacao"
    EXECUTAR_E_AVISAR = "executar_e_avisar"
    EXECUTAR = "executar"


DECISAO_POR_NIVEL = {
    Nivel.PROIBIDO: Decisao.BLOQUEAR,
    Nivel.SUGERE: Decisao.SUGERIR,
    Nivel.APROVA: Decisao.PEDIR_APROVACAO,
    Nivel.FAZ_E_AVISA: Decisao.EXECUTAR_E_AVISAR,
    Nivel.AUTONOMO: Decisao.EXECUTAR,
}

# Categorias que, por regra inviolável, nunca passam de "Aprova".
MOVER_DINHEIRO = "mover_dinheiro"
APAGAR_DADOS = "apagar_dados"
ENVIAR_DADOS_EXTERNOS = "enviar_dados_externos"
CATEGORIAS_SENSIVEIS = frozenset({MOVER_DINHEIRO, APAGAR_DADOS, ENVIAR_DADOS_EXTERNOS})


@dataclass(frozen=True)
class TipoAcao:
    nome: str
    teto: Nivel
    padrao: Nivel
    categorias: frozenset[str] = frozenset()


def _t(nome, teto, padrao, *cats) -> tuple[str, TipoAcao]:
    return nome, TipoAcao(nome, teto, padrao, frozenset(cats))


CATALOGO: dict[str, TipoAcao] = dict([
    # Nível 0 — nunca acontece, nem com aprovação.
    _t("apagar_banco", Nivel.PROIBIDO, Nivel.PROIBIDO, APAGAR_DADOS),
    _t("exportar_base_clientes", Nivel.PROIBIDO, Nivel.PROIBIDO, ENVIAR_DADOS_EXTERNOS),
    # Financeiro
    _t("baixa_titulo", Nivel.FAZ_E_AVISA, Nivel.APROVA),
    _t("estornar_baixa", Nivel.APROVA, Nivel.APROVA),
    _t("pagar_fornecedor", Nivel.APROVA, Nivel.APROVA, MOVER_DINHEIRO),
    _t("registrar_divergencia", Nivel.AUTONOMO, Nivel.AUTONOMO),
    # No Beta não há canal de envio (WhatsApp), então cobrança é só sugestão.
    _t("sugerir_cobranca", Nivel.SUGERE, Nivel.SUGERE),
    # Dono
    _t("resumir_dia", Nivel.AUTONOMO, Nivel.AUTONOMO),
])


@dataclass
class AcaoProposta:
    agente: str
    tipo: str
    descricao: str
    payload: dict
    chave: str
    valor: Decimal | None = None
    # O agente pode pedir para a ação ser tratada com MENOS autonomia (ex.: match de baixa confiança).
    nivel_maximo_pedido: Nivel | None = None
    motivo_agente: str | None = None


@dataclass
class Veredito:
    decisao: Decisao
    nivel: Nivel
    motivos: list[str] = field(default_factory=list)

    @property
    def motivo(self) -> str:
        return "; ".join(self.motivos)


class Auditor:
    def __init__(self, playbook: Playbook, catalogo: dict[str, TipoAcao] | None = None):
        self.playbook = playbook
        self.catalogo = catalogo or CATALOGO

    def avaliar(self, acao: AcaoProposta) -> Veredito:
        tipo = self.catalogo.get(acao.tipo)
        if tipo is None:
            # Negar por padrão: ação desconhecida nunca é executada.
            return Veredito(Decisao.BLOQUEAR, Nivel.PROIBIDO, [f"ação '{acao.tipo}' não está no catálogo"])

        motivos: list[str] = []
        nivel = Nivel(self.playbook.autonomia.get(tipo.nome, tipo.padrao))

        if nivel > tipo.teto:
            motivos.append(f"Playbook pediu nível {int(nivel)}, teto em código é {int(tipo.teto)}")
            nivel = tipo.teto

        if tipo.categorias & CATEGORIAS_SENSIVEIS and nivel > Nivel.APROVA:
            motivos.append("regra inviolável: mover dinheiro, apagar ou enviar dados exige aprovação")
            nivel = Nivel.APROVA

        if tipo.nome == "baixa_titulo" and acao.valor is not None:
            limite = Decimal(str(self.playbook.financeiro.baixa_automatica_ate))
            if acao.valor > limite and nivel > Nivel.APROVA:
                motivos.append(f"valor {brl(acao.valor)} acima do limite de baixa automática ({brl(limite)})")
                nivel = Nivel.APROVA

        if acao.nivel_maximo_pedido is not None and acao.nivel_maximo_pedido < nivel:
            motivos.append(acao.motivo_agente or f"agente pediu no máximo nível {int(acao.nivel_maximo_pedido)}")
            nivel = acao.nivel_maximo_pedido

        if not motivos:
            motivos.append(f"nível {int(nivel)} conforme Playbook")
        return Veredito(DECISAO_POR_NIVEL[nivel], nivel, motivos)
