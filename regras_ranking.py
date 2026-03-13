from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

DATA_LIMITE_DESAFIO = datetime(2026, 10, 21, 23, 59)
DATA_LIMITE_PARTIDA = datetime(2026, 10, 31, 23, 59)
PRAZO_DESAFIO_DIAS = 10


def _parse_dt(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except Exception:
        return None


def verificar_status_financeiro(atleta: Dict[str, Any]) -> Tuple[bool, str]:
    # Nesta versão, controle financeiro não bloqueia automaticamente.
    # O bloqueio é aplicado manualmente pela secretaria via campo dedicado.
    if atleta.get('status_financeiro') == 'atraso':
        return True, 'Financeiro em atraso (pendente de análise da secretaria).'
    return True, 'Financeiro regular.'


def verificar_status_atleta(atleta: Dict[str, Any], referencia_dt: datetime | None = None) -> Tuple[bool, str]:
    now = referencia_dt or datetime.now()

    if atleta.get('retirado'):
        return False, 'Atleta retirado do ranking.'
    if not atleta.get('ativo'):
        return False, 'Atleta inativo.'
    if atleta.get('neutro'):
        return False, 'Atleta em afastamento neutro.'
    if atleta.get('bloqueio_secretaria'):
        motivo = atleta.get('bloqueio_motivo') or 'bloqueio manual da secretaria'
        return False, f'Atleta bloqueado pela secretaria ({motivo}).'

    bloqueado_ate = _parse_dt(atleta.get('bloqueado_ate'))
    if bloqueado_ate and bloqueado_ate > now:
        return False, f"Atleta bloqueado até {bloqueado_ate.strftime('%d/%m/%Y %H:%M')}."

    return True, 'Atleta apto.'


def verificar_bloqueio_novo_desafio(atleta: Dict[str, Any], referencia_dt: datetime | None = None) -> Tuple[bool, str]:
    now = referencia_dt or datetime.now()
    bloqueado_ate = _parse_dt(atleta.get('bloqueado_ate'))
    if bloqueado_ate and bloqueado_ate > now:
        return True, f"Novo desafio bloqueado até {bloqueado_ate.strftime('%d/%m/%Y %H:%M')}"
    return False, 'Sem bloqueio para novo desafio.'


def pode_desafiar(desafiante: Dict[str, Any], desafiado: Dict[str, Any], referencia_dt: datetime | None = None) -> Tuple[bool, str]:
    now = referencia_dt or datetime.now()

    if now > DATA_LIMITE_PARTIDA:
        return False, 'Período de desafios encerrado para a temporada.'

    ok, msg = verificar_status_atleta(desafiante, now)
    if not ok:
        return False, f'Desafiante inválido: {msg}'

    ok, msg = verificar_status_atleta(desafiado, now)
    if not ok:
        return False, f'Desafiado inválido: {msg}'

    if desafiante.get('ranking') != desafiado.get('ranking'):
        return False, 'Desafio deve ocorrer no mesmo ranking/categoria.'

    pos_d = int(desafiante.get('posicao', 0) or 0)
    pos_r = int(desafiado.get('posicao', 0) or 0)

    if pos_d <= 0 or pos_r <= 0:
        return False, 'Posições inválidas para o desafio.'

    if pos_r >= pos_d:
        return False, 'Desafiante só pode desafiar atletas acima na tabela.'

    if (pos_d - pos_r) > 3:
        return False, 'Desafiante só pode desafiar até 3 posições acima.'

    bloqueado, msg_b = verificar_bloqueio_novo_desafio(desafiante, now)
    if bloqueado:
        return False, msg_b

    if now > DATA_LIMITE_DESAFIO:
        return False, 'Prazo para lançar novos desafios encerrou em 21/10/2026.'

    return True, 'Desafio válido.'


def verificar_prazo_desafio(partida: Dict[str, Any], referencia_dt: datetime | None = None, clima_adverso: bool = False) -> Tuple[bool, str]:
    now = referencia_dt or datetime.now()

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


def listar_desafios_possiveis(atleta: Dict[str, Any], atletas: List[Dict[str, Any]], referencia_dt: datetime | None = None) -> List[Dict[str, Any]]:
    now = referencia_dt or datetime.now()
    ranking = atleta.get('ranking')
    posicao = int(atleta.get('posicao', 0) or 0)

    if posicao <= 1:
        return []

    candidatos = [
        a for a in atletas
        if a.get('ranking') == ranking and int(a.get('posicao', 0) or 0) < posicao and (posicao - int(a.get('posicao', 0) or 0)) <= 3
    ]

    saida: List[Dict[str, Any]] = []
    for c in sorted(candidatos, key=lambda x: int(x.get('posicao', 999))):
        valido, motivo = pode_desafiar(atleta, c, now)
        saida.append({
            'id': c.get('id'),
            'nome': c.get('nome'),
            'posicao': c.get('posicao'),
            'classe': c.get('classe'),
            'pode_desafiar': valido,
            'motivo': motivo,
        })

    return saida
