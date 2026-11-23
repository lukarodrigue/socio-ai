"""Monta as peças (banco, Playbook, Auditor) a partir das variáveis de ambiente."""
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy.orm import sessionmaker

from .auditor import Auditor
from .config import Settings, get_settings
from .db import criar_engine, fabrica_sessao
from .playbook import carregar_playbook


@dataclass
class Contexto:
    settings: Settings
    auditor: Auditor
    Sessao: sessionmaker


@lru_cache
def contexto() -> Contexto:
    st = get_settings()
    return Contexto(st, Auditor(carregar_playbook(st.playbook_path)), fabrica_sessao(criar_engine(st.database_url)))
