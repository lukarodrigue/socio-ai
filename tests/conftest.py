from pathlib import Path

import pytest

from socio_ia.auditor import Auditor
from socio_ia.db import criar_engine, fabrica_sessao
from socio_ia.playbook import carregar_playbook

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def playbook():
    return carregar_playbook(RAIZ / "playbooks" / "empresa_ficticia.yaml")


@pytest.fixture
def auditor(playbook):
    return Auditor(playbook)


@pytest.fixture
def sessao():
    engine = criar_engine("sqlite://")
    s = fabrica_sessao(engine)()
    yield s
    s.close()
