"""Playbook: as regras de cada empresa. Validado na carga para falhar cedo."""
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class Empresa(BaseModel):
    nome: str
    cnpj: str
    fuso: str = "America/Sao_Paulo"


class Agenda(BaseModel):
    dono_inicio_dia: str = "07:00"
    financeiro_conciliacao: list[str] = ["09:00", "18:00"]
    dono_relatorio: str = "19:00"


class Financeiro(BaseModel):
    baixa_automatica_ate: float = Field(5000.0, ge=0)
    tolerancia_centavos: float = Field(0.01, ge=0)
    janela_dias_antes_vencimento: int = Field(10, ge=0)
    janela_dias_depois_vencimento: int = Field(45, ge=0)
    taxa_cartao_contratada: float = Field(0.0299, ge=0, lt=1)
    tolerancia_taxa_cartao: float = Field(0.001, ge=0)
    similaridade_nome_minima: float = Field(0.6, ge=0, le=1)


class Playbook(BaseModel):
    empresa: Empresa
    aprovadores: list[str] = Field(min_length=1)
    agenda: Agenda = Agenda()
    financeiro: Financeiro = Financeiro()
    autonomia: dict[str, int] = {}
    tom_de_voz: str = "profissional"

    @field_validator("autonomia")
    @classmethod
    def _niveis_validos(cls, v: dict[str, int]) -> dict[str, int]:
        for acao, nivel in v.items():
            if not 0 <= nivel <= 4:
                raise ValueError(f"nível de '{acao}' deve estar entre 0 e 4, veio {nivel}")
        return v


def carregar_playbook(caminho: str | Path) -> Playbook:
    with open(caminho, encoding="utf-8") as f:
        return Playbook.model_validate(yaml.safe_load(f))
