from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class StoragePaths:
    bootstrap_dir: Path
    runtime_dir: Path
    db_path: Path
    source: str
    strict_mode: bool


def _is_truthy(value: str | None) -> bool:
    return (value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def running_in_managed_production(environ: Mapping[str, str] | None = None) -> bool:
    env = environ or os.environ
    return any(
        (
            env.get('RENDER'),
            env.get('RENDER_SERVICE_ID'),
            env.get('RENDER_INSTANCE_ID'),
            env.get('IS_RENDER'),
            env.get('RENDER_EXTERNAL_URL'),
            env.get('RENDER_SERVICE_NAME'),
        )
    )


def resolve_storage_paths(base_dir: Path, environ: Mapping[str, str] | None = None) -> StoragePaths:
    env = environ or os.environ
    bootstrap_dir = base_dir / 'dados'
    configured = (env.get('DATA_DIR') or '').strip()
    strict_mode = running_in_managed_production(env) or _is_truthy(env.get('X1_BTC_REQUIRE_DATA_DIR'))

    if configured:
        runtime_dir = Path(configured)
        source = 'DATA_DIR'
    elif strict_mode:
        raise RuntimeError(
            'DATA_DIR não está configurado. Em produção/Render o X1_BTC exige Persistent Disk '
            'montado e a variável DATA_DIR apontando para esse diretório.'
        )
    else:
        runtime_dir = base_dir / '.runtime_data'
        source = 'local-default'

    if configured and not runtime_dir.exists():
        raise RuntimeError(
            f"DATA_DIR aponta para '{runtime_dir}', mas esse diretório não existe. "
            'Verifique o mount path do Persistent Disk no Render.'
        )

    runtime_dir.mkdir(parents=True, exist_ok=True)

    if not runtime_dir.is_dir():
        raise RuntimeError(f"O diretório de dados '{runtime_dir}' não é um diretório válido.")

    try:
        with tempfile.NamedTemporaryFile(dir=runtime_dir, prefix='x1_btc_write_test_', delete=True):
            pass
    except Exception as exc:  # pragma: no cover - depends on filesystem permissions
        raise RuntimeError(
            f"DATA_DIR '{runtime_dir}' não está acessível para leitura/escrita: {exc}"
        ) from exc

    return StoragePaths(
        bootstrap_dir=bootstrap_dir,
        runtime_dir=runtime_dir,
        db_path=runtime_dir / 'x1_btc.db',
        source=source,
        strict_mode=strict_mode,
    )
