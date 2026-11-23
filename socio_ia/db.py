from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from .models import Base


def criar_engine(url: str):
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            from sqlalchemy.pool import StaticPool
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    _proteger_segundo_cerebro(engine)
    return engine


def _proteger_segundo_cerebro(engine) -> None:
    """O Segundo Cérebro é só de inclusão: o próprio banco recusa UPDATE e DELETE em eventos.

    Assim a garantia não depende de nenhum agente "se comportar".
    """
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            for op in ("UPDATE", "DELETE"):
                conn.exec_driver_sql(
                    f"CREATE TRIGGER IF NOT EXISTS eventos_sem_{op.lower()} BEFORE {op} ON eventos "
                    "BEGIN SELECT RAISE(ABORT, 'Segundo Cérebro é somente inclusão'); END;"
                )
        elif engine.dialect.name == "postgresql":
            conn.exec_driver_sql(
                "CREATE OR REPLACE FUNCTION eventos_somente_inclusao() RETURNS trigger AS $$ "
                "BEGIN RAISE EXCEPTION 'Segundo Cérebro é somente inclusão'; END; $$ LANGUAGE plpgsql;"
            )
            conn.exec_driver_sql("DROP TRIGGER IF EXISTS eventos_imutaveis ON eventos;")
            conn.exec_driver_sql(
                "CREATE TRIGGER eventos_imutaveis BEFORE UPDATE OR DELETE ON eventos "
                "FOR EACH ROW EXECUTE FUNCTION eventos_somente_inclusao();"
            )


def fabrica_sessao(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
