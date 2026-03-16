from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class DataStore:
    def __init__(self, db_path: Path, bootstrap_dir: Path):
        self.db_path = db_path
        self.bootstrap_dir = bootstrap_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
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
        with self._connect() as conn:
            row = conn.execute('SELECT payload FROM datasets WHERE name = ?', (name,)).fetchone()
            if row:
                return json.loads(row['payload'])

        bootstrap_path = self.bootstrap_dir / f'{name}.json'
        if not bootstrap_path.exists():
            raise FileNotFoundError(f'Dataset não encontrado: {bootstrap_path}')
        data = json.loads(bootstrap_path.read_text(encoding='utf-8-sig'))
        self.save_dataset(name, data)
        return data

    def save_dataset(self, name: str, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        with self._connect() as conn:
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

        # Mantém um espelho em JSON para inspeção e backup local.
        bootstrap_path = self.bootstrap_dir / f'{name}.json'
        bootstrap_path.write_text(payload, encoding='utf-8')
