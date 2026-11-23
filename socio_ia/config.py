import os
from dataclasses import dataclass
from pathlib import Path

PLAYBOOK_PADRAO = Path(__file__).resolve().parent.parent / "playbooks" / "empresa_ficticia.yaml"


@dataclass(frozen=True)
class Settings:
    database_url: str
    playbook_path: str
    ollama_url: str
    ollama_model: str


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("SOCIO_DATABASE_URL", "sqlite:///socio_ia.db"),
        playbook_path=os.getenv("SOCIO_PLAYBOOK", str(PLAYBOOK_PADRAO)),
        ollama_url=os.getenv("SOCIO_OLLAMA_URL", ""),
        ollama_model=os.getenv("SOCIO_OLLAMA_MODEL", "qwen2.5:7b-instruct"),
    )
