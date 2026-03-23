from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from utils import agora_brasilia, parse_iso_brasilia

DATA_LIMITE_DESAFIO = datetime(2026, 10, 21, 23, 59)
DATA_LIMITE_PARTIDA = datetime(2026, 10, 31, 23, 59)
PRAZO_DESAFIO_DIAS = 10


def _parse_dt(valor: str | None) -> datetime | None:
    return parse_iso_brasilia(valor)


def verificar_status_financeiro(atleta: Dict[str, Any]) -> Tuple[bool, str]:
    # Nesta versão, controle financeiro não bloqueia automaticamente.
    # O bloqueio é aplicado manualmente pela secretaria via campo dedicado.
    if atleta.get('status_financeiro') == 'atraso':
        return True, 'Financeiro em atraso (pendente de análise da secretaria).'
    return True, 'Financeiro regular.'


def verificar_status_atleta(atleta: Dict[str, Any], referencia_dt: datetime | None = None) -> Tuple[bool, str]:
    if atleta.get('retirado'):
        return False, 'Atleta retirado do ranking.'
    if not atleta.get('ativo'):
        return False, 'Atleta inativo.'
    if atleta.get('neutro'):
        return False, 'Atleta em afastamento neutro.'
    if atleta.get('bloqueio_secretaria'):
        motivo = atleta.get('bloqueio_motivo') or 'bloqueio manual da secretaria'
        return False, f'Atleta bloqueado pela secretaria ({motivo}).'

    return True, 'Atleta apto.'


def verificar_bloqueio_novo_desafio(atleta: Dict[str, Any], referencia_dt: datetime | None = None) -> Tuple[bool, str]:
    now = referencia_dt or agora_brasilia()
    bloqueado_ate = _parse_dt(atleta.get('bloqueado_ate'))
    if bloqueado_ate and bloqueado_ate > now:
        return True, f"Novo desafio bloqueado até {bloqueado_ate.strftime('%d/%m/%Y %H:%M')}"
    return False, 'Sem bloqueio para novo desafio.'


def _atleta_em_desafio(partidas: List[Dict[str, Any]] | None, atleta_id: str) -> bool:
    if not partidas:
        return False
    return any(
        atleta_id in {p.get('desafiante'), p.get('desafiado')}
        and p.get('status') in {'pendente_agendamento', 'aguardando_data', 'marcada', 'em_andamento'}
        for p in partidas
    )


def _partidas_finalizadas(partidas: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    if not partidas:
        return []
    return [
        partida for partida in partidas
        if partida.get('status') in {'finalizada', 'realizada'}
        and partida.get('data_registro_resultado')
    ]


def _atletas_mesmo_ranking(atletas: List[Dict[str, Any]] | None, ranking: str | None) -> List[Dict[str, Any]]:
    if not atletas or not ranking:
        return []
    return [
        atleta for atleta in atletas
        if atleta.get('ranking') == ranking and atleta.get('ativo') and not atleta.get('retirado')
    ]


def _elegivel_para_contagem_desafio(atleta: Dict[str, Any]) -> bool:
    return atleta.get('ativo') and not atleta.get('retirado') and not atleta.get('neutro')


def listar_alvos_acima(atleta: Dict[str, Any], atletas: List[Dict[str, Any]], limite_ativos: int = 3) -> List[Dict[str, Any]]:
    ranking = atleta.get('ranking')
    posicao = int(atleta.get('posicao', 0) or 0)
    candidatos = sorted(
        [
            cand for cand in _atletas_mesmo_ranking(atletas, ranking)
            if cand.get('id') != atleta.get('id') and int(cand.get('posicao', 0) or 0) < posicao
        ],
        key=lambda cand: int(cand.get('posicao', 9999) or 9999),
        reverse=True,
    )

    saida: List[Dict[str, Any]] = []
    ativos_contados = 0
    for cand in candidatos:
        saida.append(cand)
        if _elegivel_para_contagem_desafio(cand):
            ativos_contados += 1
        if ativos_contados >= limite_ativos:
            break

    return sorted(saida, key=lambda cand: int(cand.get('posicao', 9999) or 9999))


def listar_desafiantes_abaixo(atleta: Dict[str, Any], atletas: List[Dict[str, Any]], limite_ativos: int = 3) -> List[Dict[str, Any]]:
    ranking = atleta.get('ranking')
    posicao = int(atleta.get('posicao', 0) or 0)
    candidatos = sorted(
        [
            cand for cand in _atletas_mesmo_ranking(atletas, ranking)
            if cand.get('id') != atleta.get('id') and int(cand.get('posicao', 0) or 0) > posicao
        ],
        key=lambda cand: int(cand.get('posicao', 9999) or 9999),
    )

    saida: List[Dict[str, Any]] = []
    ativos_contados = 0
    for cand in candidatos:
        saida.append(cand)
        if _elegivel_para_contagem_desafio(cand):
            ativos_contados += 1
        if ativos_contados >= limite_ativos:
            break

    return saida


def _ordem_desafio(desafiante: Dict[str, Any], desafiado: Dict[str, Any], atletas: List[Dict[str, Any]] | None) -> int | None:
    ranking = desafiante.get('ranking')
    posicao = int(desafiante.get('posicao', 0) or 0)
    candidatos = sorted(
        [
            cand for cand in _atletas_mesmo_ranking(atletas, ranking)
            if cand.get('id') != desafiante.get('id') and int(cand.get('posicao', 0) or 0) < posicao
        ],
        key=lambda cand: int(cand.get('posicao', 9999) or 9999),
        reverse=True,
    )
    ordem = 0
    for cand in candidatos:
        if _elegivel_para_contagem_desafio(cand):
            ordem += 1
        if cand.get('id') == desafiado.get('id'):
            return ordem if _elegivel_para_contagem_desafio(cand) else None
    return None


def _bloqueio_repeticao_confronto(
    partidas: List[Dict[str, Any]] | None,
    desafiante_id: str | None,
    desafiado_id: str | None,
    referencia_dt: datetime,
) -> Tuple[bool, str]:
    if not partidas or not desafiante_id or not desafiado_id:
        return False, 'Sem bloqueio de repetição.'

    historico_dupla = [
        partida for partida in _partidas_finalizadas(partidas)
        if {partida.get('desafiante'), partida.get('desafiado')} == {desafiante_id, desafiado_id}
    ]
    if not historico_dupla:
        return False, 'Sem confronto anterior entre os atletas.'

    ultimo_confronto = max(
        historico_dupla,
        key=lambda partida: _parse_dt(partida.get('data_registro_resultado')) or datetime.min,
    )
    data_ultimo = _parse_dt(ultimo_confronto.get('data_registro_resultado'))
    if not data_ultimo:
        return False, 'Sem bloqueio de repetição.'

    if referencia_dt > data_ultimo + timedelta(days=PRAZO_DESAFIO_DIAS):
        return False, 'Janela de repetição já expirou.'

    houve_outro_jogo = any(
        partida.get('id') != ultimo_confronto.get('id')
        and (desafiante_id in {partida.get('desafiante'), partida.get('desafiado')}
             or desafiado_id in {partida.get('desafiante'), partida.get('desafiado')})
        and (_parse_dt(partida.get('data_registro_resultado')) or datetime.min) > data_ultimo
        for partida in _partidas_finalizadas(partidas)
    )
    if houve_outro_jogo:
        return False, 'Atleta já fez outro jogo após o último confronto.'

    limite = (data_ultimo + timedelta(days=PRAZO_DESAFIO_DIAS)).strftime('%d/%m/%Y %H:%M')
    return True, f'Repetição do mesmo confronto bloqueada até {limite}.'


def pode_desafiar(desafiante: Dict[str, Any], desafiado: Dict[str, Any], referencia_dt: datetime | None = None) -> Tuple[bool, str]:
    return pode_desafiar_com_partidas(desafiante, desafiado, None, referencia_dt)


def pode_desafiar_com_partidas(
    desafiante: Dict[str, Any],
    desafiado: Dict[str, Any],
    partidas: List[Dict[str, Any]] | None = None,
    referencia_dt: datetime | None = None,
    atletas: List[Dict[str, Any]] | None = None,
) -> Tuple[bool, str]:
    now = referencia_dt or agora_brasilia()

    if now > DATA_LIMITE_PARTIDA:
        return False, 'Período de desafios encerrado para a temporada.'

    ok, msg = verificar_status_atleta(desafiante, now)
    if not ok:
        return False, f'Desafiante inválido: {msg}'

    ok, msg = verificar_status_atleta(desafiado, now)
    if not ok:
        return False, f'Desafiado inválido: {msg}'

    if _atleta_em_desafio(partidas, desafiante.get('id')):
        return False, 'Desafiante em desafio: já possui confronto pendente/agendado/em andamento.'

    if _atleta_em_desafio(partidas, desafiado.get('id')):
        return False, 'Desafiado em desafio: já possui confronto pendente/agendado/em andamento.'

    if desafiante.get('ranking') != desafiado.get('ranking'):
        return False, 'Desafio deve ocorrer no mesmo ranking/categoria.'

    pos_d = int(desafiante.get('posicao', 0) or 0)
    pos_r = int(desafiado.get('posicao', 0) or 0)

    if pos_d <= 0 or pos_r <= 0:
        return False, 'Posições inválidas para o desafio.'

    if pos_r >= pos_d:
        return False, 'Desafiante só pode desafiar atletas acima na tabela.'

    ordem_desafio = _ordem_desafio(desafiante, desafiado, atletas)
    if ordem_desafio is not None:
        if ordem_desafio > 3:
            return False, 'Desafiante só pode desafiar até 3 posições acima.'
    elif (pos_d - pos_r) > 3:
        return False, 'Desafiante só pode desafiar até 3 posições acima.'

    bloqueado, msg_b = verificar_bloqueio_novo_desafio(desafiante, now)
    if bloqueado:
        return False, msg_b

    repeticao_bloqueada, msg_repeticao = _bloqueio_repeticao_confronto(
        partidas,
        desafiante.get('id'),
        desafiado.get('id'),
        now,
    )
    if repeticao_bloqueada:
        return False, msg_repeticao

    if now > DATA_LIMITE_DESAFIO:
        return False, 'Prazo para lançar novos desafios encerrou em 21/10/2026.'

    return True, 'Desafio válido.'


def verificar_prazo_desafio(partida: Dict[str, Any], referencia_dt: datetime | None = None, clima_adverso: bool = False) -> Tuple[bool, str]:
    now = referencia_dt or agora_brasilia()

    dt_desafio = _parse_dt(partida.get('data_desafio'))
    dt_jogo = _parse_dt(f"{partida.get('data')}T{partida.get('horario')}:00") if partida.get('data') and partida.get('horario') else None

    if dt_jogo and dt_jogo > DATA_LIMITE_PARTIDA:
        return False, 'Data da partida ultrapassa o limite de 31/10/2026.'

    if not dt_desafio or not dt_jogo:
        return False, 'Desafio sem datas suficientes para validação de prazo.'

    prazo_base = PRAZO_DESAFIO_DIAS + (2 if clima_adverso else 0)
    prazo_final = dt_desafio + timedelta(days=prazo_base)

    if dt_jogo > prazo_final:
        return False, f'Partida fora do prazo de {prazo_base} dias do desafio.'

    if now > DATA_LIMITE_PARTIDA:
        return False, 'Temporada encerrada para partidas válidas.'

    return True, 'Prazo de desafio válido.'


def aplicar_wo_consecutivo(atleta: Dict[str, Any], atletas_categoria: List[Dict[str, Any]]) -> Dict[str, Any]:
    atleta['wo_consecutivos'] = int(atleta.get('wo_consecutivos', 0) or 0) + 1

    if atleta['wo_consecutivos'] >= 3:
        ultima_pos = max(int(a.get('posicao', 0) or 0) for a in atletas_categoria)
        atleta['posicao'] = ultima_pos
        atleta['wo_consecutivos'] = 0
        atleta['observacoes'] = (atleta.get('observacoes', '') + ' Rebaixado ao fim da categoria por 3 WO consecutivos.').strip()

    return atleta


def listar_desafios_possiveis(
    atleta: Dict[str, Any],
    atletas: List[Dict[str, Any]],
    referencia_dt: datetime | None = None,
    partidas: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    now = referencia_dt or agora_brasilia()
    ranking = atleta.get('ranking')
    posicao = int(atleta.get('posicao', 0) or 0)

    if posicao <= 1:
        return []

    candidatos = listar_alvos_acima(atleta, atletas, limite_ativos=3)

    saida: List[Dict[str, Any]] = []
    atleta_em_confronto = _atleta_em_desafio(partidas, atleta.get('id'))

    for c in candidatos:
        if atleta_em_confronto:
            valido, motivo = False, 'Em desafio: atleta já possui confronto em andamento/agendado.'
        else:
            valido, motivo = pode_desafiar_com_partidas(atleta, c, partidas, now, atletas)
        saida.append({
            'id': c.get('id'),
            'nome': c.get('nome'),
            'posicao': c.get('posicao'),
            'classe': c.get('classe'),
            'pode_desafiar': valido,
            'motivo': motivo,
        })

    return saida
