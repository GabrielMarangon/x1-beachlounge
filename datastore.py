from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import pg8000
except Exception:  # pragma: no cover
    pg8000 = None


class DataStore:
    def __init__(self, db_path: Path, bootstrap_dir: Path, mirror_dir: Path | None = None):
        self.db_path = db_path
        self.bootstrap_dir = bootstrap_dir
        self.mirror_dir = mirror_dir or bootstrap_dir
        self.database_url = os.getenv('DATABASE_URL', '').strip()
        self.backend = 'postgres' if self.database_url else 'sqlite'

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.mirror_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _mirror_path(self, name: str) -> Path:
        return self.mirror_dir / f'{name}.json'

    def _nonempty_backup_path(self, name: str) -> Path:
        return self.mirror_dir / f'{name}.last_nonempty.json'

    def _read_json_file(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding='utf-8-sig'))

    def _restore_nonempty_backup_if_needed(self, name: str, data: Any) -> Any:
        if name != 'partidas':
            return data
        if not isinstance(data, list) or data:
            return data

        backup_path = self._nonempty_backup_path(name)
        if not backup_path.exists():
            return data

        backup_data = self._read_json_file(backup_path)
        if isinstance(backup_data, list) and backup_data:
            self.save_dataset(name, backup_data)
            return backup_data
        return data

    def _sqlite_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _postgres_connect(self):
        if pg8000 is None:
            raise RuntimeError('pg8000 não instalado. Adicione a dependência para usar DATABASE_URL.')
        parsed = urlparse(self.database_url.replace('postgres://', 'postgresql://'))
        return pg8000.connect(
            user=parsed.username,
            password=parsed.password,
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=(parsed.path or '/').lstrip('/'),
        )

    def _init_db(self) -> None:
        if self.backend == 'postgres':
            with self._postgres_connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS datasets (
                        name TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    '''
                )
                conn.commit()
            return

        with self._sqlite_connect() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS datasets (
                    name TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            conn.commit()

    def load_dataset(self, name: str) -> Any:
        if self.backend == 'postgres':
            with self._postgres_connect() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT payload FROM datasets WHERE name = %s', (name,))
                row = cursor.fetchone()
                if row:
                    return self._restore_nonempty_backup_if_needed(name, json.loads(row[0]))
        else:
            with self._sqlite_connect() as conn:
                row = conn.execute('SELECT payload FROM datasets WHERE name = ?', (name,)).fetchone()
                if row:
                    return self._restore_nonempty_backup_if_needed(name, json.loads(row['payload']))

        mirror_path = self._mirror_path(name)
        if mirror_path.exists():
            data = self._read_json_file(mirror_path)
            data = self._restore_nonempty_backup_if_needed(name, data)
            self.save_dataset(name, data)
            return data

        backup_path = self._nonempty_backup_path(name)
        if name == 'partidas' and backup_path.exists():
            data = self._read_json_file(backup_path)
            if isinstance(data, list) and data:
                self.save_dataset(name, data)
                return data

        bootstrap_path = self.bootstrap_dir / f'{name}.json'
        if not bootstrap_path.exists():
            raise FileNotFoundError(f'Dataset não encontrado: {bootstrap_path}')
        data = self._read_json_file(bootstrap_path)
        data = self._restore_nonempty_backup_if_needed(name, data)
        self.save_dataset(name, data)
        return data

    def save_dataset(self, name: str, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2)

        if self.backend == 'postgres':
            with self._postgres_connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO datasets(name, payload, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (name) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        updated_at = CURRENT_TIMESTAMP
                    ''',
                    (name, payload),
                )
                conn.commit()
        else:
            with self._sqlite_connect() as conn:
                conn.execute(
                    '''
                    INSERT INTO datasets(name, payload, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(name) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = CURRENT_TIMESTAMP
                    ''',
                    (name, payload),
                )
                conn.commit()

        mirror_path = self._mirror_path(name)
        mirror_path.write_text(payload, encoding='utf-8')
        if isinstance(data, list) and data:
            self._nonempty_backup_path(name).write_text(payload, encoding='utf-8')
