from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from regras_ranking import aplicar_wo_consecutivo
from utils import atletas_ativos_do_ranking, normalizar_posicoes_ranking


def _categoria_atletas(atletas: List[Dict[str, Any]], ranking: str) -> List[Dict[str, Any]]:
    return atletas_ativos_do_ranking(atletas, ranking)


def _ordenar_posicoes(categoria: List[Dict[str, Any]]) -> None:
    categoria.sort(key=lambda x: int(x.get('posicao', 9999) or 9999))
    for i, a in enumerate(categoria, start=1):
        a['posicao'] = i


def processar_vitoria_desafiante(atletas: List[Dict[str, Any]], desafiante_id: str, desafiado_id: str) -> None:
    desafiante = next(a for a in atletas if a['id'] == desafiante_id)
    desafiado = next(a for a in atletas if a['id'] == desafiado_id)

    ranking = desafiante['ranking']
    categoria = _categoria_atletas(atletas, ranking)

    pos_d = int(desafiante['posicao'])
    pos_r = int(desafiado['posicao'])

    if pos_r >= pos_d:
        return

    for a in categoria:
        p = int(a['posicao'])
        if pos_r <= p < pos_d:
            a['posicao'] = p + 1

    desafiante['posicao'] = pos_r
    _ordenar_posicoes(categoria)


def processar_vitoria_desafiado(atletas: List[Dict[str, Any]], desafiante_id: str, desafiado_id: str) -> None:
    desafiante = next(a for a in atletas if a['id'] == desafiante_id)
    desafiado = next(a for a in atletas if a['id'] == desafiado_id)
    desafiante['wo_consecutivos'] = 0
    desafiado['wo_consecutivos'] = 0


def processar_wo(atletas: List[Dict[str, Any]], perdedor_id: str, ranking: str) -> None:
    perdedor = next(a for a in atletas if a['id'] == perdedor_id)
    categoria = _categoria_atletas(atletas, ranking)
    aplicar_wo_consecutivo(perdedor, categoria)
    _ordenar_posicoes(categoria)


def atualizar_ranking_apos_resultado(partida: Dict[str, Any], atletas: List[Dict[str, Any]]) -> Tuple[bool, str]:
    desafiante_id = partida.get('desafiante')
    desafiado_id = partida.get('desafiado')
    vencedor_id = partida.get('vencedor')
    ranking = partida.get('categoria')
    wo = bool(partida.get('wo'))

    if not desafiante_id or not desafiado_id or not vencedor_id:
        return False, 'Dados insuficientes para atualizar ranking.'

    desafiante = next((a for a in atletas if a['id'] == desafiante_id), None)
    desafiado = next((a for a in atletas if a['id'] == desafiado_id), None)
    if not desafiante or not desafiado:
        return False, 'Atletas não encontrados para atualização de ranking.'

    now = datetime.now()

    if vencedor_id == desafiante_id:
        processar_vitoria_desafiante(atletas, desafiante_id, desafiado_id)
        if wo:
            processar_wo(atletas, desafiado_id, ranking)
    else:
        processar_vitoria_desafiado(atletas, desafiante_id, desafiado_id)
        if wo:
            processar_wo(atletas, desafiante_id, ranking)

    normalizar_posicoes_ranking(atletas, ranking)

    desafiante['ultimo_jogo'] = now.isoformat(timespec='minutes')
    desafiado['ultimo_jogo'] = now.isoformat(timespec='minutes')

    # Regra: desafiante aguarda ate meio-dia do dia seguinte para novo desafio.
    bloqueio = (now + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    desafiante['bloqueado_ate'] = bloqueio.isoformat(timespec='minutes')
    desafiante['ultimo_desafio'] = now.isoformat(timespec='minutes')
    desafiado['ultimo_desafio'] = now.isoformat(timespec='minutes')

    partida['status'] = 'finalizada'
    partida['data_registro_resultado'] = now.isoformat(timespec='minutes')

    return True, 'Ranking atualizado com sucesso.'
