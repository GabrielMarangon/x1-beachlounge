from __future__ import annotations

import gc
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from datastore import DataStore
from storage_config import resolve_storage_paths


class StorageConfigTests(unittest.TestCase):
    def test_require_data_dir_in_managed_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            (base_dir / 'dados').mkdir()
            env = {
                'RENDER_SERVICE_ID': 'srv-test',
            }
            with self.assertRaisesRegex(RuntimeError, 'DATA_DIR'):
                resolve_storage_paths(base_dir, env)

    def test_local_default_runtime_dir_when_not_in_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            (base_dir / 'dados').mkdir()
            paths = resolve_storage_paths(base_dir, {})
            self.assertEqual(paths.runtime_dir, base_dir / '.runtime_data')
            self.assertTrue(paths.runtime_dir.exists())
            self.assertEqual(paths.source, 'local-default')


class DataStorePersistenceTests(unittest.TestCase):
    def _write_bootstrap(self, bootstrap_dir: Path, dataset_name: str, payload: object) -> None:
        bootstrap_dir.mkdir(parents=True, exist_ok=True)
        (bootstrap_dir / f'{dataset_name}.json').write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    def test_runtime_state_wins_over_bootstrap_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_dir = root / 'bootstrap'
            runtime_dir = root / 'runtime'
            self._write_bootstrap(bootstrap_dir, 'atletas', [{'id': 'a1', 'nome': 'Original'}])

            store = DataStore(runtime_dir / 'x1_btc.db', bootstrap_dir, runtime_dir)
            atletas = store.load_dataset('atletas')
            atletas.append({'id': 'a2', 'nome': 'Persistido'})
            store.save_dataset('atletas', atletas)

            self._write_bootstrap(bootstrap_dir, 'atletas', [{'id': 'a9', 'nome': 'Seed alterado'}])

            restarted_store = DataStore(runtime_dir / 'x1_btc.db', bootstrap_dir, runtime_dir)
            persisted = restarted_store.load_dataset('atletas')

            self.assertEqual([item['id'] for item in persisted], ['a1', 'a2'])
            del store
            del restarted_store
            gc.collect()

    def test_legacy_bootstrap_runtime_is_migrated_once_when_runtime_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_dir = root / 'bootstrap'
            runtime_dir = root / 'runtime'
            self._write_bootstrap(bootstrap_dir, 'partidas', [{'id': 'p001'}])

            store = DataStore(runtime_dir / 'x1_btc.db', bootstrap_dir, runtime_dir)
            partidas = store.load_dataset('partidas')

            self.assertEqual(partidas, [{'id': 'p001'}])
            self.assertTrue((runtime_dir / 'partidas.json').exists())
            self.assertTrue((runtime_dir / 'x1_btc.db').exists())
            del store
            gc.collect()

    def test_existing_runtime_data_is_not_overwritten_by_legacy_bootstrap_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_dir = root / 'bootstrap'
            runtime_dir = root / 'runtime'
            self._write_bootstrap(bootstrap_dir, 'partidas', [{'id': 'bootstrap'}])
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / 'partidas.json').write_text(
                json.dumps([{'id': 'runtime'}], ensure_ascii=False, indent=2),
                encoding='utf-8',
            )

            store = DataStore(runtime_dir / 'x1_btc.db', bootstrap_dir, runtime_dir)
            partidas = store.load_dataset('partidas')

            self.assertEqual(partidas, [{'id': 'runtime'}])
            del store
            gc.collect()


if __name__ == '__main__':
    unittest.main()
