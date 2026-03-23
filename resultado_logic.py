from __future__ import annotations

from typing import Any, Dict, List, Tuple

from utils import agora_brasilia, indice_por_id, normalizar_posicoes_ranking


def reverter_resultado_com_snapshot(partida: Dict[str, Any], atletas: List[Dict[str, Any]]) -> Tuple[bool, str]:
    if partida.get('status') not in {'finalizada', 'realizada'}:
        return False, 'Somente partidas com resultado lançado podem ser apagadas.'

    snapshot = partida.get('snapshot_pre_resultado')
    if not isinstance(snapshot, dict) or not snapshot:
        return False, (
            'Este resultado não pode ser revertido automaticamente porque foi salvo sem snapshot histórico. '
            'Para esse caso legado, o ajuste precisa ser feito manualmente pela secretaria.'
        )

    atletas_map = indice_por_id(atletas)
    for atleta_id, estado in snapshot.items():
        atleta = atletas_map.get(atleta_id)
        if not atleta:
            continue
        atleta['posicao'] = estado.get('posicao')
        atleta['wo_consecutivos'] = estado.get('wo_consecutivos', 0)
        atleta['ultimo_jogo'] = estado.get('ultimo_jogo')
        atleta['ultimo_desafio'] = estado.get('ultimo_desafio')
        atleta['bloqueado_ate'] = estado.get('bloqueado_ate')
        atleta['observacoes'] = estado.get('observacoes', '')

    normalizar_posicoes_ranking(atletas, partida.get('categoria'))

    era_wo_automatico = (
        partida.get('wo')
        and (partida.get('resultado') or '').strip() == 'W.O. por prazo expirado'
    )

    if era_wo_automatico:
        partida['status'] = 'desconsiderada'
        partida['observacoes'] = 'Partida desconsiderada manualmente após reversão de W.O. automático por prazo expirado.'
        mensagem = 'W.O. automático revertido e partida movida para desconsiderada.'
    else:
        partida['status'] = partida.get('status_antes_resultado', 'marcada')
        mensagem = 'Resultado apagado e ranking revertido com sucesso.'

    partida['resultado'] = None
    partida['vencedor'] = None
    partida['wo'] = False
    partida['data_registro_resultado'] = None
    partida['resultado_apagado_em'] = agora_brasilia().isoformat(timespec='minutes')
    partida.pop('snapshot_pre_resultado', None)
    partida.pop('status_antes_resultado', None)

    return True, mensagem
