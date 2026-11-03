from typing import cast

from alembic import context
from sqlalchemy.engine import Connection


def run() -> None:
    """Upgrade only through the caller's already-owned transactional connection."""
    connection = cast(Connection, context.config.attributes["connection"])
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()


run()
