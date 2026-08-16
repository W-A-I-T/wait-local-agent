from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

MigrationApply = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: MigrationApply
    foreign_keys_off: bool = False


class MigrationRunner:
    """Apply ordered SQLite migrations exactly once and transactionally."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def run(self, migrations: Iterable[Migration]) -> None:
        ordered = tuple(migrations)
        self._validate(ordered)
        self.connection.execute(
            """
            create table if not exists schema_migrations (
                version integer primary key,
                name text not null,
                applied_at text not null
            )
            """
        )
        applied = {
            int(row[0])
            for row in self.connection.execute("select version from schema_migrations")
        }
        for migration in ordered:
            if migration.version in applied:
                continue
            foreign_keys_state: int | None = None
            if migration.foreign_keys_off:
                foreign_keys_state = int(self.connection.execute("pragma foreign_keys").fetchone()[0])
                self.connection.execute("pragma foreign_keys = off")
            try:
                self.connection.execute("begin")
                try:
                    migration.apply(self.connection)
                    self.connection.execute(
                        "insert into schema_migrations (version, name, applied_at) values (?, ?, ?)",
                        (migration.version, migration.name, datetime.now(UTC).isoformat()),
                    )
                except BaseException:
                    self.connection.rollback()
                    raise
                else:
                    self.connection.commit()
            finally:
                if foreign_keys_state is not None:
                    self.connection.execute(
                        f"pragma foreign_keys = {'on' if foreign_keys_state else 'off'}"
                    )
            applied.add(migration.version)

    @staticmethod
    def _validate(migrations: tuple[Migration, ...]) -> None:
        versions = [migration.version for migration in migrations]
        if versions != sorted(set(versions)):
            raise ValueError("migrations must have unique, strictly increasing versions")
        if any(migration.version < 0 or not migration.name.strip() for migration in migrations):
            raise ValueError("migrations require a non-negative version and non-empty name")
