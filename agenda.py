from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Tuple

from regras_ranking import pode_desafiar_com_partidas, verificar_prazo_desafio
from utils import agora_brasilia, gerar_id_partida


def _parse_game_dt(data: str, horario: str) -> datetime:
    return datetime.strptime(f"{data} {horario}", '%Y-%m-%d %H:%M')


def verificar_conflito_quadras(partidas: List[Dict[str, Any]], data: str, horario: str, quadra: str, partida_id_ignorar: str | None = None) -> Tuple[bool, str]:
    for p in partidas:
        if partida_id_ignorar and p.get('id') == partida_id_ignorar:
            continue
        if p.get('status') in {'cancelada', 'desconsiderada'}:
            continue
        if p.get('data') == data and p.get('horario') == horario and p.get('quadra') == quadra:
            return True, 'Conflito: quadra já ocupada nesse horário.'
    return False, 'Sem conflito de quadra.'


def verificar_conflito_atleta(partidas: List[Dict[str, Any]], data: str, horario: str, atleta_id: str, partida_id_ignorar: str | None = None) -> Tuple[bool, str]:
    for p in partidas:
        if partida_id_ignorar and p.get('id') == partida_id_ignorar:
            continue
        if p.get('status') in {'cancelada', 'desconsiderada'}:
            continue
        if p.get('data') == data and p.get('horario') == horario and atleta_id in {p.get('desafiante'), p.get('desafiado')}:
            return True, 'Conflito: atleta já possui jogo nesse horário.'
    return False, 'Sem conflito de atleta.'


def listar_horarios_disponiveis(partidas: List[Dict[str, Any]], quadras: List[Dict[str, Any]], horarios: List[Dict[str, Any]], data: str) -> List[Dict[str, Any]]:
    disponiveis: List[Dict[str, Any]] = []
    for q in quadras:
        for h in horarios:
            ocupado = any(
                p.get('data') == data and p.get('horario') == h['hora'] and p.get('quadra') == q['id'] and p.get('status') in {'marcada', 'em_andamento'}
                for p in partidas
            )
            disponiveis.append({
                'data': data,
                'quadra': q['id'],
                'quadra_nome': q['nome'],
                'horario': h['hora'],
                'livre': not ocupado,
            })
    return disponiveis


def agendar_partida(
    atletas: List[Dict[str, Any]],
    partidas: List[Dict[str, Any]],
    payload: Dict[str, Any],
) -> Tuple[bool, str, Dict[str, Any] | None]:
    desafiante = next((a for a in atletas if a.get('id') == payload.get('desafiante')), None)
    desafiado = next((a for a in atletas if a.get('id') == payload.get('desafiado')), None)

    if not desafiante or not desafiado:
        return False, 'Desafiante ou desafiado não encontrado.', None

    valido, msg = pode_desafiar_com_partidas(desafiante, desafiado, partidas)
    if not valido:
        return False, msg, None

    data = payload.get('data')
    horario = payload.get('horario')
    quadra = payload.get('quadra')
    status = payload.get('status', 'marcada')

    sem_data_definida = status == 'aguardando_data' or not data
    if sem_data_definida:
        partida = {
            'id': gerar_id_partida(partidas),
            'desafiante': desafiante['id'],
            'desafiado': desafiado['id'],
            'data': '',
            'horario': '',
            'quadra': '',
            'categoria': desafiante.get('ranking'),
            'tipo_confronto': payload.get('tipo_confronto', 'ranking_x1'),
            'status': 'aguardando_data',
            'resultado': None,
            'vencedor': None,
            'wo': False,
            'data_registro_resultado': None,
            'data_desafio': agora_brasilia().isoformat(timespec='minutes'),
            'observacoes': payload.get('observacoes', ''),
        }
        partidas.append(partida)
        return True, 'Partida registrada sem data definida.', partida

    try:
        _parse_game_dt(data, horario)
    except Exception:
        return False, 'Data/horário inválidos.', None

    conflito_q, msg_q = verificar_conflito_quadras(partidas, data, horario, quadra)
    if conflito_q:
        return False, msg_q, None

    conflito_d, msg_d = verificar_conflito_atleta(partidas, data, horario, desafiante['id'])
    if conflito_d:
        return False, msg_d, None

    conflito_r, msg_r = verificar_conflito_atleta(partidas, data, horario, desafiado['id'])
    if conflito_r:
        return False, msg_r, None

    partida = {
        'id': gerar_id_partida(partidas),
        'desafiante': desafiante['id'],
        'desafiado': desafiado['id'],
        'data': data,
        'horario': horario,
        'quadra': quadra,
        'categoria': desafiante.get('ranking'),
        'tipo_confronto': payload.get('tipo_confronto', 'ranking_x1'),
        'status': status,
        'resultado': None,
        'vencedor': None,
        'wo': False,
        'data_registro_resultado': None,
        'data_desafio': agora_brasilia().isoformat(timespec='minutes'),
        'observacoes': payload.get('observacoes', ''),
    }

    ok_prazo, msg_prazo = verificar_prazo_desafio(partida)
    if not ok_prazo:
        return False, msg_prazo, None

    partidas.append(partida)
    return True, 'Partida agendada com sucesso.', partida


def listar_partidas_marcadas(partidas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [p for p in partidas if p.get('status') in {'marcada', 'em_andamento'}]


def listar_partidas_por_data(partidas: List[Dict[str, Any]], data: str) -> List[Dict[str, Any]]:
    return [p for p in partidas if p.get('data') == data]


def listar_partidas_por_atleta(partidas: List[Dict[str, Any]], atleta_id: str) -> List[Dict[str, Any]]:
    return [p for p in partidas if atleta_id in {p.get('desafiante'), p.get('desafiado')}]
