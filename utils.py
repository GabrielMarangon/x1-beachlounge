import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def carregar_json(path: Path) -> Any:
    with path.open('r', encoding='utf-8-sig') as f:
        return json.load(f)


def salvar_json(path: Path, data: Any) -> None:
    with path.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def formatar_status(atleta: Dict[str, Any]) -> Dict[str, str]:
    if atleta.get('retirado'):
        return {'label': 'retirado', 'cor': 'cinza'}
    if not atleta.get('ativo'):
        return {'label': 'inativo', 'cor': 'cinza'}
    if atleta.get('neutro'):
        return {'label': 'neutro', 'cor': 'amarelo'}
    if atleta.get('bloqueio_secretaria'):
        return {'label': 'bloqueado pela secretaria', 'cor': 'vermelho'}
    if atleta.get('bloqueado_ate'):
        try:
            if datetime.fromisoformat(atleta['bloqueado_ate']) > datetime.now():
                return {'label': 'bloqueado temporariamente', 'cor': 'vermelho'}
        except Exception:
            pass
    if atleta.get('status_financeiro') == 'atraso':
        return {'label': 'pendência financeira (análise da secretaria)', 'cor': 'amarelo'}
    return {'label': 'apto', 'cor': 'verde'}


def ordenar_partidas_por_data(partidas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _key(p: Dict[str, Any]):
        dt_txt = f"{p.get('data', '')} {p.get('horario', '')}".strip()
        try:
            return datetime.strptime(dt_txt, '%Y-%m-%d %H:%M')
        except Exception:
            return datetime.max

    return sorted(partidas, key=_key)


def indice_por_id(itens: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {x['id']: x for x in itens if x.get('id')}


def gerar_id_partida(partidas: List[Dict[str, Any]]) -> str:
    nums = []
    for p in partidas:
        pid = str(p.get('id', ''))
        if pid.startswith('p') and pid[1:].isdigit():
            nums.append(int(pid[1:]))
    n = (max(nums) + 1) if nums else 1
    return f"p{n:03d}"
