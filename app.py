from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from agenda import (
    agendar_partida,
    listar_horarios_disponiveis,
    listar_partidas_marcadas,
    listar_partidas_por_atleta,
    listar_partidas_por_data,
    verificar_conflito_atleta,
    verificar_conflito_quadras,
)
from datastore import DataStore
from ranking_logic import (
    aplicar_wo_automatico_partidas_vencidas,
    atualizar_ranking_apos_resultado,
)
from resultado_logic import reverter_resultado_com_snapshot
from regras_ranking import (
    listar_desafiantes_abaixo,
    listar_desafios_possiveis,
    pode_desafiar_com_partidas,
    verificar_status_atleta,
)
from storage_config import StoragePaths, resolve_storage_paths
from utils import (
    agora_brasilia,
    atletas_ativos_do_ranking,
    formatar_placar_por_ordem_da_partida,
    formatar_status,
    gerar_id_partida,
    indice_por_id,
    normalizar_posicoes_ranking,
    ordenar_partidas_por_data,
)

BASE_DIR = Path(__file__).resolve().parent


def _configure_logging() -> logging.Logger:
    logging.basicConfig(
        level=os.getenv('LOG_LEVEL', 'INFO').upper(),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    return logging.getLogger('x1_beachlounge')


LOGGER = _configure_logging()
STORAGE: StoragePaths = resolve_storage_paths(BASE_DIR)
BOOTSTRAP_DATA_DIR = STORAGE.bootstrap_dir
RUNTIME_DATA_DIR = STORAGE.runtime_dir
DB_PATH = STORAGE.db_path
STORE = DataStore(DB_PATH, BOOTSTRAP_DATA_DIR, RUNTIME_DATA_DIR)

LOGGER.info('Bootstrap de dados configurado em: %s', BOOTSTRAP_DATA_DIR)
LOGGER.info('Diretorio operacional configurado em: %s', RUNTIME_DATA_DIR)
LOGGER.info('Banco operacional configurado em: %s', DB_PATH)
LOGGER.info(
    'Persistencia inicializada via %s (modo estrito=%s).',
    STORAGE.source,
    STORAGE.strict_mode,
)

RANKING_ROTULOS = {
    'masculina': 'Masculina',
    'feminina': 'Feminina',
    'kids_ate_12_anos': 'Kids até 12 anos',
}
ATHLETE_PHONE_FIXTURES = {
    ('masculina', 'DANIEL CORREA'): '55981664757',
    ('masculina', 'MEC'): '55984399196',
    ('masculina', 'ROGER S'): '55996135933',
    ('masculina', 'JUNIOR'): '55999163770',
    ('masculina', 'GABRIEL DAHLEN'): '51983057370',
    ('masculina', 'NASSER AHAMED'): '55999254976',
    ('masculina', 'DENNER'): '55999480474',
    ('masculina', 'PEDRO VINADE'): '55999870605',
    ('masculina', 'VINICIUS GUEDES'): '55999285581',
    ('masculina', 'GABRIEL DEL OLMO'): '55997324358',
    ('masculina', 'GUI KURBAN'): '55999954650',
    ('masculina', 'RICARDO POSSEBON'): '',
    ('masculina', 'CAROL MACHADO'): '55996097614',
    ('masculina', 'MARCELO B'): '55999751340',
    ('masculina', 'CARLINHOS'): '55999653525',
    ('masculina', 'POLONES'): '55991069180',
    ('masculina', 'YURI'): '55996957693',
    ('masculina', 'JOAO PAULO'): '55984581475',
    ('masculina', 'MARTIN'): '',
    ('masculina', 'FABRICIO'): '55991371974',
    ('masculina', 'JERUSA'): '55999992606',
    ('masculina', 'MATHEUS FERREIRA'): '5596288089',
    ('masculina', 'BRUNO OLIVEIRA'): '55991969607',
    ('masculina', 'CLARISSA JORGE'): '55996871696',
    ('masculina', 'ISA'): '55996959689',
    ('masculina', 'RICARDO AIRES'): '55997166898',
    ('masculina', 'DEBORA'): '55999468894',
    ('masculina', 'ANNA JULIA'): '55996436415',
    ('masculina', 'GUI SALDANHA'): '55997056873',
    ('masculina', 'GON?ALO'): '55999163770',
    ('feminina', 'CAROL MACHADO'): '55996097614',
    ('feminina', 'JERUSA'): '55999992606',
    ('feminina', 'DEBORA'): '55999468894',
    ('feminina', 'CLARISSA JORGE'): '55996871696',
    ('masculina', 'GABRIELA MACHADO'): '55996475532',
    ('feminina', 'GABRIELA MACHADO'): '55996475532',
    ('feminina', 'ISA'): '55996959689',
    ('feminina', 'ISABELY MACHADO'): '55991846771',
    ('feminina', 'ANNA JULIA'): '55996436415',
    ('kids_ate_12_anos', 'GON?ALO'): '55999163770',
    ('kids_ate_12_anos', 'MARTIN'): '55992372957',
    ('kids_ate_12_anos', 'WILL'): '55991066214',
    ('kids_ate_12_anos', 'YASSER AHAMED'): '55999254976',
}
SECRETARIA_USERNAME = os.getenv('SECRETARIA_USERNAME', 'secretaria_beach').strip()
SECRETARIA_PASSWORD_HASH = os.getenv('SECRETARIA_PASSWORD_HASH', '').strip()
SECRETARIA_PASSWORD = os.getenv('SECRETARIA_PASSWORD', 'BeachSecretaria@2026').strip()
ACCESS_LOG_LIMIT = 2000


def _load_all() -> Dict[str, Any]:
    quadras, quadras_sync = STORE.sync_dataset_from_bootstrap('quadras')
    horarios, horarios_sync = STORE.sync_dataset_from_bootstrap('horarios')
    if quadras_sync or horarios_sync:
        LOGGER.info(
            'Datasets de refer?ncia sincronizados do bootstrap (quadras=%s, horarios=%s).',
            quadras_sync,
            horarios_sync,
        )

    data = {
        'atletas': STORE.load_dataset('atletas'),
        'quadras': quadras,
        'horarios': horarios,
        'partidas': STORE.load_dataset('partidas'),
    }
    if _backfill_known_athlete_phones(data['atletas']):
        _save_atletas(data['atletas'])
    _aplicar_wo_automatico_por_prazo(data)
    normalizar_posicoes_ranking(data['atletas'])
    return data


def _snapshot_ranking_categoria(atletas: List[Dict[str, Any]], ranking_partida: str | None) -> Dict[str, Dict[str, Any]]:
    snapshot: Dict[str, Dict[str, Any]] = {}
    for atleta in atletas:
        if atleta.get('ranking') != ranking_partida:
            continue
        snapshot[atleta['id']] = {
            'posicao': atleta.get('posicao'),
            'wo_consecutivos': atleta.get('wo_consecutivos'),
            'ultimo_jogo': atleta.get('ultimo_jogo'),
            'ultimo_desafio': atleta.get('ultimo_desafio'),
            'bloqueado_ate': atleta.get('bloqueado_ate'),
            'observacoes': atleta.get('observacoes'),
        }
    return snapshot


def _aplicar_wo_automatico_por_prazo(data: Dict[str, Any]) -> None:
    candidatas = []
    for partida in data['partidas']:
        if partida.get('status') not in {'pendente_agendamento', 'aguardando_data', 'marcada', 'em_andamento'}:
            continue
        if partida.get('snapshot_pre_resultado'):
            continue
        partida['status_antes_resultado'] = partida.get('status', 'marcada')
        partida['snapshot_pre_resultado'] = _snapshot_ranking_categoria(data['atletas'], partida.get('categoria'))
        candidatas.append(partida)

    processadas = aplicar_wo_automatico_partidas_vencidas(data['partidas'], data['atletas'])
    processadas_ids = {partida.get('id') for partida in processadas}
    for partida in candidatas:
        if partida.get('id') in processadas_ids:
            continue
        partida.pop('snapshot_pre_resultado', None)
        partida.pop('status_antes_resultado', None)

    if not processadas:
        return

    _save_atletas(data['atletas'])
    _save_partidas(data['partidas'])


def _rotulo_status_partida(partida: Dict[str, Any]) -> str:
    status = partida.get('status') or ''
    resultado = (partida.get('resultado') or '').strip()
    observacoes = (partida.get('observacoes') or '').lower()
    if partida.get('wo') and (
        resultado == 'W.O. por prazo expirado' or 'prazo expirado' in observacoes
    ):
        return 'W.O. automático por prazo expirado'
    if status == 'marcada':
        return 'Marcada'
    if status == 'pendente_agendamento':
        return 'Pendente de agendamento'
    if status == 'aguardando_data':
        return 'Sem data definida'
    if status == 'finalizada':
        return 'Finalizada'
    if status == 'desconsiderada':
        return 'Desconsiderada'
    if status == 'cancelada':
        return 'Cancelada'
    if status == 'em_andamento':
        return 'Em andamento'
    if status == 'realizada':
        return 'Realizada'
    return status or '-'


def _save_atletas(atletas: List[Dict[str, Any]]) -> None:
    STORE.save_dataset('atletas', atletas)


def _save_partidas(partidas: List[Dict[str, Any]]) -> None:
    STORE.save_dataset('partidas', partidas)


def _normalize_identity_text(value: str | None) -> str:
    texto = unicodedata.normalize('NFKD', (value or '').strip())
    texto = ''.join(ch for ch in texto if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', texto).strip().casefold()


def _normalize_phone(value: str | None) -> str:
    return re.sub(r'\D+', '', value or '')


KNOWN_ATHLETE_PHONES = {
    (ranking, _normalize_identity_text(nome)): _normalize_phone(telefone)
    for (ranking, nome), telefone in ATHLETE_PHONE_FIXTURES.items()
}


def _backfill_known_athlete_phones(atletas: List[Dict[str, Any]]) -> bool:
    changed = False
    for atleta in atletas:
        key = (atleta.get('ranking'), _normalize_identity_text(atleta.get('nome')))
        telefone_conhecido = KNOWN_ATHLETE_PHONES.get(key)
        if not telefone_conhecido:
            continue
        telefone_atual = _normalize_phone(atleta.get('telefone'))
        if telefone_atual == telefone_conhecido:
            continue
        if telefone_atual:
            continue
        atleta['telefone'] = telefone_conhecido
        changed = True
    return changed


def _athlete_public_payload(atleta: Dict[str, Any]) -> Dict[str, Any]:
    publico = dict(atleta)
    publico.pop('telefone', None)
    return publico


def _clear_athlete_session() -> None:
    session.pop('atleta_autenticado', None)
    session.pop('atleta_nome', None)
    session.pop('atleta_ids', None)


def _bind_athlete_session(atletas: List[Dict[str, Any]]) -> None:
    ids = sorted({atleta.get('id') for atleta in atletas if atleta.get('id')})
    if not ids:
        _clear_athlete_session()
        return
    session['atleta_autenticado'] = True
    session['atleta_nome'] = atletas[0].get('nome', '')
    session['atleta_ids'] = ids


def _session_athlete_ids() -> set[str]:
    ids = session.get('atleta_ids') or []
    return {item for item in ids if isinstance(item, str) and item}


def _session_user_type() -> str:
    if session.get('secretaria_autorizada'):
        return 'secretaria'
    if session.get('atleta_autenticado') and _session_athlete_ids():
        return 'atleta'
    return 'visitante'


def _find_athletes_by_identity(nome: str, contato: str, atletas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nome_normalizado = _normalize_identity_text(nome)
    contato_normalizado = _normalize_phone(contato)
    if not nome_normalizado or not contato_normalizado:
        return []
    return [
        atleta
        for atleta in atletas
        if _normalize_identity_text(atleta.get('nome')) == nome_normalizado
        and _normalize_phone(atleta.get('telefone')) == contato_normalizado
        and not atleta.get('retirado')
    ]


def _name_matches_registered_athlete(nome: str, atletas: List[Dict[str, Any]]) -> bool:
    nome_normalizado = _normalize_identity_text(nome)
    if not nome_normalizado:
        return False
    return any(
        _normalize_identity_text(atleta.get('nome')) == nome_normalizado and not atleta.get('retirado')
        for atleta in atletas
    )


def _actor_can_manage_atleta(atleta_id: str) -> bool:
    if session.get('secretaria_autorizada'):
        return True
    return atleta_id in _session_athlete_ids()


def _actor_can_manage_partida(partida: Dict[str, Any]) -> bool:
    if session.get('secretaria_autorizada'):
        return True
    ids = _session_athlete_ids()
    return bool(ids.intersection({partida.get('desafiante'), partida.get('desafiado')}))


def _load_access_logs() -> List[Dict[str, Any]]:
    try:
        logs = STORE.load_dataset('access_logs')
        return logs if isinstance(logs, list) else []
    except FileNotFoundError:
        return []


def _save_access_logs(logs: List[Dict[str, Any]]) -> None:
    STORE.save_dataset('access_logs', list(deque(logs, maxlen=ACCESS_LOG_LIMIT)))


def _client_ip() -> str:
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'desconhecido'


def _visitor_identity() -> Dict[str, str]:
    return {
        'nome': (session.get('atleta_nome') if _session_user_type() == 'atleta' else session.get('visitante_nome', '')).strip(),
        'contato': session.get('visitante_contato', '').strip(),
        'tipo': _session_user_type(),
    }


def _log_access(evento: str) -> None:
    if request.endpoint == 'health' or request.path.startswith('/static/'):
        return

    logs = _load_access_logs()
    visitante = _visitor_identity()
    logs.append({
        'timestamp': agora_brasilia().isoformat(timespec='seconds'),
        'evento': evento,
        'rota': request.path,
        'metodo': request.method,
        'ip': _client_ip(),
        'nome': visitante['nome'],
        'contato': visitante['contato'],
        'tipo_usuario': visitante['tipo'],
        'user_agent': request.headers.get('User-Agent', '')[:240],
    })
    _save_access_logs(logs)


def _secretaria_configurada() -> bool:
    return bool(SECRETARIA_USERNAME and (SECRETARIA_PASSWORD_HASH or SECRETARIA_PASSWORD))


def _validar_login_secretaria(usuario: str, senha: str) -> bool:
    if not _secretaria_configurada():
        return False
    if usuario != SECRETARIA_USERNAME:
        return False
    if SECRETARIA_PASSWORD_HASH:
        return check_password_hash(SECRETARIA_PASSWORD_HASH, senha)
    return senha == SECRETARIA_PASSWORD


def _slugify(texto: str) -> str:
    base = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii')
    base = re.sub(r'[^a-zA-Z0-9]+', '_', base.lower()).strip('_')
    return base or 'atleta'


def _classe_masculina_por_posicao(posicao: int) -> str:
    indice = max(1, ((max(1, posicao) - 1) // 10) + 1)
    return f'{indice}ª Classe'


def _classe_por_ranking_posicao(ranking: str, posicao: int) -> str:
    if ranking == 'masculino_principal':
        return _classe_masculina_por_posicao(posicao)
    return RANKING_ROTULOS.get(ranking, ranking)


def _inserir_atleta_em_posicao(atletas: List[Dict[str, Any]], atleta_novo: Dict[str, Any]) -> Dict[str, Any]:
    ranking = atleta_novo['ranking']
    ativos = sorted(
        [a for a in atletas if a.get('ranking') == ranking and a.get('ativo') and not a.get('retirado')],
        key=lambda item: int(item.get('posicao', 9999) or 9999),
    )
    ultima_posicao = max([int(a.get('posicao', 0) or 0) for a in ativos], default=0)
    posicao = int(atleta_novo.get('posicao', ultima_posicao + 1) or ultima_posicao + 1)
    posicao = max(1, min(posicao, ultima_posicao + 1))

    for atleta in ativos:
        if int(atleta.get('posicao', 0) or 0) >= posicao:
            atleta['posicao'] = int(atleta.get('posicao', 0) or 0) + 1

    atleta_novo['posicao'] = posicao
    atleta_novo['classe'] = _classe_por_ranking_posicao(ranking, posicao)
    atletas.append(atleta_novo)

    if ranking in {'masculino_principal', 'masculina', 'feminina', 'kids_ate_12_anos'}:
        ativos_ordenados = sorted(
            [a for a in atletas if a.get('ranking') == ranking and a.get('ativo') and not a.get('retirado')],
            key=lambda item: int(item.get('posicao', 9999) or 9999),
        )
        for atleta in ativos_ordenados:
            atleta['classe'] = _classe_por_ranking_posicao(ranking, int(atleta.get('posicao', 0) or 0))

    return atleta_novo


def _candidatos_que_podem_desafiar(atleta: Dict[str, Any], atletas: List[Dict[str, Any]], partidas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidatos = listar_desafiantes_abaixo(atleta, atletas, limite_ativos=3)

    saida = []
    for cand in sorted(candidatos, key=lambda item: int(item.get('posicao', 999))):
        valido, motivo = pode_desafiar_com_partidas(cand, atleta, partidas, atletas=atletas)
        saida.append({
            'id': cand.get('id'),
            'nome': cand.get('nome'),
            'posicao': cand.get('posicao'),
            'classe': cand.get('classe'),
            'pode_desafiar': valido,
            'motivo': motivo,
        })
    return saida


def _recalcular_classes_ranking(atletas: List[Dict[str, Any]], ranking: str) -> None:
    if ranking not in {'masculino_principal', 'masculina', 'feminina', 'kids_ate_12_anos'}:
        return
    for atleta in atletas:
        if atleta.get('ranking') == ranking and atleta.get('ativo') and not atleta.get('retirado'):
            atleta['classe'] = _classe_por_ranking_posicao(ranking, int(atleta.get('posicao', 0) or 0))


def _resumo_home(data: Dict[str, Any]) -> Dict[str, Any]:
    partidas = data['partidas']
    atletas = data['atletas']
    quadras = data['quadras']
    agora = agora_brasilia()
    hoje = agora.strftime('%Y-%m-%d')

    atletas_map = indice_por_id(atletas)
    quadras_map = indice_por_id(quadras)

    jogos_hoje_base = [p for p in partidas if p.get('data') == hoje and p.get('status') == 'marcada']
    jogos_hoje = [_enriquecer_partida(p, atletas_map, quadras_map) for p in jogos_hoje_base]
    jogos_hoje = sorted(jogos_hoje, key=lambda x: x.get('horario', '99:99'))

    pendentes_resultado = [p for p in partidas if p.get('status') == 'marcada' and datetime.strptime(p['data'], '%Y-%m-%d') < agora]
    pendentes_resultado = [_enriquecer_partida(p, atletas_map, quadras_map) for p in pendentes_resultado]
    pendentes_resultado = ordenar_partidas_por_data(pendentes_resultado)

    por_categoria = {}
    for rk in RANKING_ROTULOS:
        por_categoria[rk] = len(atletas_ativos_do_ranking(atletas, rk))

    horarios_livres = listar_horarios_disponiveis(partidas, quadras, data['horarios'], hoje)
    total_livres = len([h for h in horarios_livres if h.get('livre')])
    livres_por_quadra: Dict[str, List[str]] = {}
    for slot in horarios_livres:
        if not slot.get('livre'):
            continue
        nome_q = slot.get('quadra_nome', slot.get('quadra', 'Quadra'))
        livres_por_quadra.setdefault(nome_q, []).append(slot.get('horario'))

    ultimos_resultados = [
        _enriquecer_partida(p, atletas_map, quadras_map)
        for p in partidas
        if p.get('status') in {'finalizada', 'realizada'}
    ]
    ultimos_resultados = sorted(
        ultimos_resultados,
        key=lambda p: f"{p.get('data', '')} {p.get('horario', '')}",
        reverse=True,
    )[:5]

    top5_masculino = sorted(
        atletas_ativos_do_ranking(atletas, 'masculino_principal'),
        key=lambda x: int(x.get('posicao', 999)),
    )[:5]

    return {
        'jogos_hoje': jogos_hoje,
        'pendentes_resultado': pendentes_resultado,
        'ativos_por_categoria': por_categoria,
        'horarios_livres_hoje': total_livres,
        'horarios_livres_por_quadra': [
            {'quadra': q, 'horarios': hs}
            for q, hs in sorted(livres_por_quadra.items(), key=lambda x: x[0])
        ],
        'ultimos_resultados': ultimos_resultados,
        'top5_masculino': top5_masculino,
    }


def _enriquecer_partida(partida: Dict[str, Any], atletas_map: Dict[str, Dict[str, Any]], quadras_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    p = dict(partida)
    d = atletas_map.get(p.get('desafiante'), {})
    r = atletas_map.get(p.get('desafiado'), {})
    q = quadras_map.get(p.get('quadra'), {})
    p['desafiante_nome'] = d.get('nome', p.get('desafiante'))
    p['desafiado_nome'] = r.get('nome', p.get('desafiado'))
    p['quadra_nome'] = q.get('nome', p.get('quadra'))
    p['categoria_label'] = RANKING_ROTULOS.get(p.get('categoria'), p.get('categoria'))
    p['status_exibicao'] = _rotulo_status_partida(p)
    p['resultado_reversivel'] = bool(
        p.get('status') in {'finalizada', 'realizada'}
        and isinstance(p.get('snapshot_pre_resultado'), dict)
        and p.get('snapshot_pre_resultado')
    )
    return p


def _estatisticas_atleta(atleta_id: str, partidas: List[Dict[str, Any]]) -> Dict[str, int]:
    vitorias = 0
    derrotas = 0
    jogos_finalizados = 0

    for p in partidas:
        participa = p.get('desafiante') == atleta_id or p.get('desafiado') == atleta_id
        if not participa or p.get('status') not in {'finalizada', 'realizada'}:
            continue

        jogos_finalizados += 1
        vencedor = p.get('vencedor')
        if vencedor == atleta_id:
            vitorias += 1
        elif vencedor:
            derrotas += 1

    return {
        'jogos_finalizados': jogos_finalizados,
        'vitorias': vitorias,
        'derrotas': derrotas,
    }


def _montar_painel_secretaria(data: Dict[str, Any]) -> Dict[str, Any]:
    atletas_map = indice_por_id(data['atletas'])
    quadras_map = indice_por_id(data['quadras'])

    pendentes = [
        _enriquecer_partida(p, atletas_map, quadras_map)
        for p in data['partidas']
        if p.get('status') in {'pendente_agendamento', 'aguardando_data'}
    ]
    pendentes = sorted(pendentes, key=lambda p: p.get('data_desafio', ''), reverse=True)

    desconsideradas = [
        _enriquecer_partida(p, atletas_map, quadras_map)
        for p in data['partidas']
        if p.get('status') == 'desconsiderada'
    ]
    desconsideradas = ordenar_partidas_por_data(desconsideradas)

    partidas_marcadas = [
        _enriquecer_partida(p, atletas_map, quadras_map)
        for p in data['partidas']
        if p.get('status') == 'marcada'
    ]
    partidas_marcadas = ordenar_partidas_por_data(partidas_marcadas)

    todas_partidas = [
        _enriquecer_partida(p, atletas_map, quadras_map)
        for p in data['partidas']
        if p.get('status') != 'cancelada'
    ]
    todas_partidas = ordenar_partidas_por_data(todas_partidas)

    acessos = sorted(_load_access_logs(), key=lambda item: item.get('timestamp', ''), reverse=True)[:120]

    return {
        'atletas': data['atletas'],
        'pendentes': pendentes,
        'desconsideradas': desconsideradas,
        'partidas_marcadas': partidas_marcadas,
        'todas_partidas': todas_partidas,
        'acessos': acessos,
    }


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv('FLASK_SECRET_KEY') or os.getenv('SECRET_KEY') or 'x1-beachlounge-dev-key'

    @app.before_request
    def before_request() -> Any:
        if request.endpoint == 'health' or request.path.startswith('/static/'):
            return None

        identificacao_livre = {
            'identificacao_page',
            'registrar_identificacao',
            'login_secretaria_page',
            'login_secretaria',
            'logout_secretaria',
            'health',
            'health_storage',
        }
        exige_identificacao = request.endpoint not in identificacao_livre
        if (
            request.method == 'GET'
            and exige_identificacao
            and not session.get('visitante_nome')
            and not request.path.startswith('/api/')
        ):
            return redirect(url_for('identificacao_page', next=request.full_path or request.path))

        secretaria_protegida = (
            request.path == '/secretaria'
            or request.path.startswith('/api/secretaria/')
        )
        if secretaria_protegida and not session.get('secretaria_autorizada'):
            if request.path.startswith('/api/'):
                return jsonify({'ok': False, 'mensagem': 'Acesso restrito à secretaria.'}), 403
            return redirect(url_for('login_secretaria_page', next=request.full_path or request.path))

        # Evita gravação síncrona de log a cada abertura de página pública.
        # Esse I/O em toda navegação deixa o app sensivelmente mais lento no Render.
        # Mantemos os logs explícitos de ações críticas (login, secretaria e APIs administrativas).
        if (
            request.method == 'GET'
            and not request.path.startswith('/api/')
            and request.path.startswith('/secretaria')
        ):
            _log_access('pagina_secretaria')
        return None

    @app.route('/')
    def index():
        data = _load_all()
        return render_template(
            'index.html',
            resumo=_resumo_home(data),
            ranking_rotulos=RANKING_ROTULOS,
            visitante=_visitor_identity(),
            secretaria_autorizada=bool(session.get('secretaria_autorizada')),
        )

    @app.route('/identificacao')
    def identificacao_page():
        return render_template('identificacao.html', next_url=request.args.get('next', '/'))

    @app.route('/identificacao', methods=['POST'])
    def registrar_identificacao():
        nome = (request.form.get('nome') or '').strip()
        contato = (request.form.get('contato') or '').strip()
        next_url = request.form.get('next_url') or '/'
        if not nome:
            return render_template('identificacao.html', erro='Informe seu nome para acessar.', next_url=next_url), 400

        data = _load_all()
        atletas = data['atletas']
        if _name_matches_registered_athlete(nome, atletas):
            if not _normalize_phone(contato):
                return render_template(
                    'identificacao.html',
                    erro='Para acessar como atleta, informe o telefone cadastrado no ranking.',
                    next_url=next_url,
                ), 400
            atletas_vinculados = _find_athletes_by_identity(nome, contato, atletas)
            if not atletas_vinculados:
                return render_template(
                    'identificacao.html',
                    erro='Nome e telefone não conferem com o cadastro do atleta. Se precisar, peça atualização para a secretaria.',
                    next_url=next_url,
                ), 401
            _bind_athlete_session(atletas_vinculados)
        else:
            _clear_athlete_session()

        session['visitante_nome'] = nome
        session['visitante_contato'] = contato
        _log_access('identificacao')
        return redirect(next_url if next_url.startswith('/') else '/')

    @app.route('/ranking')
    def ranking_page():
        return render_template('ranking.html', ranking_rotulos=RANKING_ROTULOS)

    @app.route('/regulamento')
    def regulamento_page():
        return render_template('regulamento.html')

    @app.route('/agenda')
    def agenda_page():
        data = _load_all()
        return render_template('agenda.html', quadras=data['quadras'])

    @app.route('/atleta/<atleta_id>')
    def atleta_page(atleta_id: str):
        return render_template('atleta.html', atleta_id=atleta_id)

    @app.route('/partidas')
    def partidas_page():
        data = _load_all()
        return render_template('partidas.html', ranking_rotulos=RANKING_ROTULOS, quadras=data['quadras'])

    @app.route('/resultado-atleta')
    def resultado_atleta_page():
        return render_template('resultado_atleta.html')

    @app.route('/login-secretaria')
    def login_secretaria_page():
        return render_template(
            'login_secretaria.html',
            next_url=request.args.get('next', '/secretaria'),
            configurada=_secretaria_configurada(),
        )

    @app.route('/login-secretaria', methods=['POST'])
    def login_secretaria():
        usuario = (request.form.get('usuario') or '').strip()
        senha = request.form.get('senha') or ''
        next_url = request.form.get('next_url') or '/secretaria'

        if not _secretaria_configurada():
            return render_template(
                'login_secretaria.html',
                erro='Credenciais da secretaria ainda não foram configuradas no servidor.',
                next_url=next_url,
                configurada=False,
            ), 400

        if not _validar_login_secretaria(usuario, senha):
            _log_access('falha_login_secretaria')
            return render_template(
                'login_secretaria.html',
                erro='Usuário ou senha inválidos.',
                next_url=next_url,
                configurada=True,
            ), 401

        session['secretaria_autorizada'] = True
        session['secretaria_usuario'] = usuario
        session['visitante_nome'] = 'Secretaria Beach'
        session['visitante_contato'] = ''
        _log_access('login_secretaria')
        return redirect(next_url if next_url.startswith('/') else '/secretaria')

    @app.route('/logout-secretaria', methods=['POST'])
    def logout_secretaria():
        session.pop('secretaria_autorizada', None)
        session.pop('secretaria_usuario', None)
        _log_access('logout_secretaria')
        return redirect('/')

    @app.route('/secretaria')
    def secretaria_page():
        data = _load_all()
        return render_template(
            'secretaria.html',
            ranking_rotulos=RANKING_ROTULOS,
            quadras=data['quadras'],
            horarios=data['horarios'],
            secretaria_usuario=session.get('secretaria_usuario', ''),
        )

    @app.route('/desafio')
    def desafio_page():
        return render_template('desafio.html')

    @app.route('/api/sessao')
    def api_sessao():
        data = _load_all()
        ids = _session_athlete_ids()
        atletas_vinculados = [
            _athlete_public_payload(atleta)
            for atleta in data['atletas']
            if atleta.get('id') in ids
        ]
        return jsonify({
            'ok': True,
            'tipo_usuario': _session_user_type(),
            'secretaria_autorizada': bool(session.get('secretaria_autorizada')),
            'atleta_autenticado': bool(session.get('atleta_autenticado') and ids),
            'visitante_nome': session.get('visitante_nome', ''),
            'visitante_contato': session.get('visitante_contato', ''),
            'atleta_ids': sorted(ids),
            'atletas_vinculados': atletas_vinculados,
        })

    @app.route('/health')
    def health():
        return {'status': 'ok'}, 200

    @app.route('/health/storage')
    def health_storage():
        runtime_files = sorted(path.name for path in RUNTIME_DATA_DIR.glob('*') if path.is_file())
        return jsonify({
            'status': 'ok',
            'storage': {
                'bootstrap_dir': str(BOOTSTRAP_DATA_DIR),
                'runtime_dir': str(RUNTIME_DATA_DIR),
                'db_path': str(DB_PATH),
                'source': STORAGE.source,
                'strict_mode': STORAGE.strict_mode,
                'runtime_exists': RUNTIME_DATA_DIR.exists(),
                'runtime_writable': os.access(RUNTIME_DATA_DIR, os.W_OK),
                'runtime_files': runtime_files,
            },
        }), 200

    @app.route('/api/ranking')
    def api_ranking():
        data = _load_all()
        ranking = request.args.get('ranking')
        atletas = [_athlete_public_payload(atleta) for atleta in data['atletas'] if not atleta.get('retirado')]

        if ranking:
            atletas = [a for a in atletas if a.get('ranking') == ranking]

        atletas = sorted(atletas, key=lambda x: (x.get('ranking', ''), int(x.get('posicao', 999))))
        for a in atletas:
            a['status_visual'] = formatar_status(a)
        return jsonify(atletas)

    @app.route('/api/atletas')
    def api_atletas():
        data = _load_all()
        atletas = [_athlete_public_payload(atleta) for atleta in data['atletas']]
        for a in atletas:
            a['status_visual'] = formatar_status(a)
        return jsonify(atletas)

    @app.route('/api/atleta/<atleta_id>')
    def api_atleta(atleta_id: str):
        data = _load_all()
        atletas = data['atletas']
        partidas = data['partidas']
        atleta = next((a for a in atletas if a.get('id') == atleta_id), None)
        if not atleta:
            return jsonify({'erro': 'Atleta não encontrado'}), 404

        ok, msg = verificar_status_atleta(atleta)
        desafios = listar_desafios_possiveis(atleta, atletas_ativos_do_ranking(atletas, atleta.get('ranking')), partidas=partidas)
        pode_ser_desafiado_por = _candidatos_que_podem_desafiar(atleta, atletas, partidas)

        hist = listar_partidas_por_atleta(partidas, atleta_id)
        hist = ordenar_partidas_por_data(hist)
        stats = _estatisticas_atleta(atleta_id, partidas)

        return jsonify({
            'atleta': _athlete_public_payload(atleta),
            'status_visual': formatar_status(atleta),
            'liberado_para_jogar': ok,
            'motivo_status': msg,
            'bloqueio_secretaria': bool(atleta.get('bloqueio_secretaria')),
            'bloqueio_motivo': atleta.get('bloqueio_motivo', ''),
            'desafios_possiveis': desafios,
            'pode_ser_desafiado_por': pode_ser_desafiado_por,
            'historico_partidas': hist,
            'proximos_jogos': [p for p in hist if p.get('status') == 'marcada'],
            'estatisticas': stats,
        })

    @app.route('/api/desafios/<atleta_id>')
    def api_desafios(atleta_id: str):
        if not _actor_can_manage_atleta(atleta_id):
            return jsonify({'ok': False, 'mensagem': 'Você só pode acessar os desafios do seu próprio perfil.'}), 403
        data = _load_all()
        atletas = data['atletas']
        partidas = data['partidas']
        atleta = next((a for a in atletas if a['id'] == atleta_id), None)
        if not atleta:
            return jsonify({'erro': 'Atleta não encontrado'}), 404
        candidatos = atletas_ativos_do_ranking(atletas, atleta.get('ranking'))
        return jsonify(listar_desafios_possiveis(atleta, candidatos, partidas=partidas))

    @app.route('/api/agenda')
    def api_agenda():
        data = _load_all()
        data_ref = request.args.get('data') or agora_brasilia().strftime('%Y-%m-%d')
        slots = listar_horarios_disponiveis(data['partidas'], data['quadras'], data['horarios'], data_ref)
        return jsonify(slots)

    @app.route('/api/partidas')
    def api_partidas():
        data = _load_all()
        atletas_map = indice_por_id(data['atletas'])
        quadras_map = indice_por_id(data['quadras'])
        partidas = [_enriquecer_partida(p, atletas_map, quadras_map) for p in data['partidas']]

        data_f = request.args.get('data')
        categoria_f = request.args.get('categoria')
        quadra_f = request.args.get('quadra')
        atleta_f = request.args.get('atleta')
        include_canceladas = (request.args.get('include_canceladas') or '').lower() in {'1', 'true', 'sim', 'yes'}

        if data_f:
            partidas = [p for p in partidas if p.get('data') == data_f]
        if categoria_f:
            partidas = [p for p in partidas if p.get('categoria') == categoria_f]
        if quadra_f:
            partidas = [p for p in partidas if p.get('quadra') == quadra_f]
        if atleta_f:
            low = atleta_f.lower()
            partidas = [p for p in partidas if low in p.get('desafiante_nome', '').lower() or low in p.get('desafiado_nome', '').lower()]

        partidas = ordenar_partidas_por_data(partidas)
        if not include_canceladas:
            partidas = [p for p in partidas if p.get('status') != 'cancelada']
        return jsonify(partidas)

    @app.route('/api/partidas-atleta/<atleta_id>')
    def api_partidas_atleta(atleta_id: str):
        if not _actor_can_manage_atleta(atleta_id):
            return jsonify({'ok': False, 'mensagem': 'Você só pode acessar as partidas do seu próprio perfil.'}), 403
        data = _load_all()
        atleta = next((a for a in data['atletas'] if a.get('id') == atleta_id), None)
        if not atleta:
            return jsonify({'ok': False, 'mensagem': 'Atleta não encontrado.'}), 404

        atletas_map = indice_por_id(data['atletas'])
        quadras_map = indice_por_id(data['quadras'])
        partidas_atleta = listar_partidas_por_atleta(data['partidas'], atleta_id)
        partidas_atleta = [_enriquecer_partida(p, atletas_map, quadras_map) for p in partidas_atleta]
        partidas_atleta = ordenar_partidas_por_data(partidas_atleta)

        lancaveis = [p for p in partidas_atleta if p.get('status') in {'marcada', 'em_andamento'}]
        historico = [p for p in partidas_atleta if p.get('status') in {'finalizada', 'realizada'}]

        return jsonify({
            'ok': True,
            'atleta': _athlete_public_payload(atleta),
            'lancaveis': lancaveis,
            'historico': historico,
            'estatisticas': _estatisticas_atleta(atleta_id, data['partidas']),
        })

    @app.route('/api/agendar', methods=['POST'])
    def api_agendar():
        data = _load_all()
        payload = request.get_json(silent=True) or {}
        sem_data_definida = bool(payload.get('sem_data_definida')) or not payload.get('data')
        horarios_validos = {h.get('hora') for h in data['horarios']}
        if not sem_data_definida and payload.get('horario') not in horarios_validos:
            return jsonify({
                'ok': False,
                'mensagem': f"Horário inválido. Use apenas: {', '.join(sorted(horarios_validos))}.",
            }), 400
        if sem_data_definida:
            payload['data'] = ''
            payload['horario'] = ''
            payload['quadra'] = ''
            payload['status'] = 'aguardando_data'
        ok, msg, partida = agendar_partida(data['atletas'], data['partidas'], payload)
        if not ok:
            return jsonify({'ok': False, 'mensagem': msg}), 400
        _save_partidas(data['partidas'])
        return jsonify({'ok': True, 'mensagem': msg, 'partida': partida})

    @app.route('/api/secretaria/desafios-pendentes')
    def api_desafios_pendentes_secretaria():
        data = _load_all()
        return jsonify(_montar_painel_secretaria(data)['pendentes'])

    @app.route('/api/secretaria/painel')
    def api_secretaria_painel():
        data = _load_all()
        return jsonify(_montar_painel_secretaria(data))

    @app.route('/api/secretaria/partidas-desconsideradas')
    def api_partidas_desconsideradas_secretaria():
        data = _load_all()
        return jsonify(_montar_painel_secretaria(data)['desconsideradas'])

    @app.route('/api/secretaria/acessos')
    def api_secretaria_acessos():
        return jsonify(sorted(_load_access_logs(), key=lambda item: item.get('timestamp', ''), reverse=True)[:120])

    @app.route('/api/secretaria/atletas', methods=['POST'])
    def api_secretaria_inserir_atleta():
        _log_access('api_secretaria_inserir_atleta')
        data = _load_all()
        payload = request.get_json(silent=True) or {}

        nome = (payload.get('nome') or '').strip()
        telefone = _normalize_phone(payload.get('telefone'))
        ranking = (payload.get('ranking') or '').strip()
        if not nome:
            return jsonify({'ok': False, 'mensagem': 'Informe o nome do atleta.'}), 400
        if ranking not in RANKING_ROTULOS:
            return jsonify({'ok': False, 'mensagem': 'Categoria de ranking inválida.'}), 400
        if not telefone:
            return jsonify({'ok': False, 'mensagem': 'Informe o telefone do atleta para liberar o acesso ao sistema.'}), 400

        try:
            posicao = int(payload.get('posicao'))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'mensagem': 'Informe uma posição válida para o ranking.'}), 400

        atletas = data['atletas']
        nome_normalizado = nome.casefold()
        existe = next(
            (
                atleta for atleta in atletas
                if (atleta.get('nome') or '').strip().casefold() == nome_normalizado
                and atleta.get('ranking') == ranking
                and not atleta.get('retirado')
            ),
            None,
        )
        if existe:
            return jsonify({'ok': False, 'mensagem': 'Já existe um atleta ativo com esse nome nesta categoria.'}), 400

        base_id = _slugify(nome)
        atleta_id = base_id
        contador = 2
        ids_existentes = {atleta.get('id') for atleta in atletas}
        while atleta_id in ids_existentes:
            atleta_id = f'{base_id}_{contador}'
            contador += 1

        atleta_novo = {
            'id': atleta_id,
            'nome': nome,
            'ranking': ranking,
            'categoria': RANKING_ROTULOS.get(ranking, ranking),
            'posicao': posicao,
            'classe': _classe_por_ranking_posicao(ranking, posicao),
            'ativo': True,
            'retirado': False,
            'neutro': False,
            'telefone': telefone,
            'wo_consecutivos': 0,
            'status_financeiro': payload.get('status_financeiro') or 'em dia',
            'bloqueio_secretaria': False,
            'bloqueio_motivo': '',
            'ultimo_jogo': None,
            'ultimo_desafio': None,
            'bloqueado_ate': None,
            'observacoes': payload.get('observacoes', ''),
        }

        _inserir_atleta_em_posicao(atletas, atleta_novo)
        normalizar_posicoes_ranking(atletas, ranking)
        _recalcular_classes_ranking(atletas, ranking)

        _save_atletas(atletas)
        return jsonify({'ok': True, 'mensagem': 'Novo atleta inserido com sucesso.', 'atleta': atleta_novo})

    @app.route('/api/secretaria/atletas/editar', methods=['POST'])
    def api_secretaria_editar_atleta():
        _log_access('api_secretaria_editar_atleta')
        data = _load_all()
        payload = request.get_json(silent=True) or {}

        atleta = next((a for a in data['atletas'] if a.get('id') == payload.get('atleta_id')), None)
        if not atleta:
            return jsonify({'ok': False, 'mensagem': 'Atleta não encontrado.'}), 404

        nome = (payload.get('nome') or '').strip()
        if not nome:
            return jsonify({'ok': False, 'mensagem': 'Informe o novo nome do atleta.'}), 400

        nome_normalizado = nome.casefold()
        ranking = atleta.get('ranking')
        existe = next(
            (
                outro for outro in data['atletas']
                if outro.get('id') != atleta.get('id')
                and outro.get('ranking') == ranking
                and not outro.get('retirado')
                and (outro.get('nome') or '').strip().casefold() == nome_normalizado
            ),
            None,
        )
        if existe:
            return jsonify({'ok': False, 'mensagem': 'Já existe um atleta ativo com esse nome nesta categoria.'}), 400

        atleta['nome'] = nome
        if 'observacoes' in payload:
            atleta['observacoes'] = payload.get('observacoes', '')

        _save_atletas(data['atletas'])
        return jsonify({'ok': True, 'mensagem': 'Nome do atleta atualizado com sucesso.', 'atleta': atleta})

    @app.route('/api/secretaria/atletas/retirar', methods=['POST'])
    def api_secretaria_retirar_atleta():
        _log_access('api_secretaria_retirar_atleta')
        data = _load_all()
        payload = request.get_json(silent=True) or {}

        atleta = next((a for a in data['atletas'] if a.get('id') == payload.get('atleta_id')), None)
        if not atleta:
            return jsonify({'ok': False, 'mensagem': 'Atleta não encontrado.'}), 404

        if atleta.get('retirado'):
            return jsonify({'ok': False, 'mensagem': 'Esse atleta já está retirado do ranking.'}), 400

        confronto_ativo = next(
            (
                partida for partida in data['partidas']
                if partida.get('status') in {'pendente_agendamento', 'aguardando_data', 'marcada', 'em_andamento'}
                and atleta.get('id') in {partida.get('desafiante'), partida.get('desafiado')}
            ),
            None,
        )
        if confronto_ativo:
            return jsonify({
                'ok': False,
                'mensagem': 'O atleta possui confronto ativo. Resolva ou exclua a partida antes de retirá-lo do ranking.',
            }), 400

        atleta['retirado'] = True
        atleta['ativo'] = False
        atleta['neutro'] = False
        atleta['bloqueio_secretaria'] = False
        atleta['bloqueio_motivo'] = ''
        atleta['observacoes'] = (payload.get('observacoes') or '').strip() or 'Atleta retirado do ranking pela secretaria.'

        normalizar_posicoes_ranking(data['atletas'], atleta.get('ranking'))
        _recalcular_classes_ranking(data['atletas'], atleta.get('ranking'))
        _save_atletas(data['atletas'])
        return jsonify({'ok': True, 'mensagem': 'Atleta retirado do ranking com sucesso.', 'atleta': atleta})

    @app.route('/api/desafio/registrar', methods=['POST'])
    def api_registrar_desafio_para_secretaria():
        _log_access('api_secretaria_desafio_registrar')
        data = _load_all()
        payload = request.get_json(silent=True) or {}
        desafiante_id = payload.get('desafiante_id')
        desafiado_id = payload.get('desafiado_id')
        if not desafiante_id or not desafiado_id:
            return jsonify({'ok': False, 'mensagem': 'Desafiante e desafiado são obrigatórios.'}), 400
        if not session.get('secretaria_autorizada') and not _actor_can_manage_atleta(desafiante_id):
            return jsonify({'ok': False, 'mensagem': 'Você só pode gerar desafio em nome do seu próprio perfil.'}), 403

        atletas = data['atletas']
        desafiante = next((a for a in atletas if a.get('id') == desafiante_id), None)
        desafiado = next((a for a in atletas if a.get('id') == desafiado_id), None)
        if not desafiante or not desafiado:
            return jsonify({'ok': False, 'mensagem': 'Atletas não encontrados.'}), 404

        valido, motivo = pode_desafiar_com_partidas(desafiante, desafiado, data['partidas'], atletas=data['atletas'])
        if not valido:
            return jsonify({'ok': False, 'mensagem': motivo}), 400

        existente = next(
            (
                p for p in data['partidas']
                if p.get('status') in {'pendente_agendamento', 'aguardando_data', 'marcada', 'em_andamento'}
                and p.get('desafiante') == desafiante_id
                and p.get('desafiado') == desafiado_id
            ),
            None,
        )
        if existente:
            return jsonify({'ok': True, 'mensagem': 'Desafio já está na fila da secretaria.', 'partida': existente})

        partida = {
            'id': gerar_id_partida(data['partidas']),
            'desafiante': desafiante_id,
            'desafiado': desafiado_id,
            'data': '',
            'horario': '',
            'quadra': '',
            'categoria': desafiante.get('ranking'),
            'tipo_confronto': 'ranking_x1',
            'status': 'pendente_agendamento',
            'resultado': None,
            'vencedor': None,
            'wo': False,
            'data_registro_resultado': None,
            'data_desafio': agora_brasilia().isoformat(timespec='minutes'),
            'observacoes': payload.get('observacoes', ''),
        }
        data['partidas'].append(partida)
        _save_partidas(data['partidas'])
        return jsonify({'ok': True, 'mensagem': 'Desafio enviado para agendamento da secretaria.', 'partida': partida})

    @app.route('/api/secretaria/agendar-pendente', methods=['POST'])
    def api_agendar_pendente_secretaria():
        _log_access('api_secretaria_agendar_pendente')
        data = _load_all()
        payload = request.get_json(silent=True) or {}
        partida_id = payload.get('partida_id')
        if not partida_id:
            return jsonify({'ok': False, 'mensagem': 'Partida pendente não informada.'}), 400

        partida = next((p for p in data['partidas'] if p.get('id') == partida_id), None)
        if not partida:
            return jsonify({'ok': False, 'mensagem': 'Partida pendente não encontrada.'}), 404
        if partida.get('status') not in {'pendente_agendamento', 'aguardando_data'}:
            return jsonify({'ok': False, 'mensagem': 'Partida não está pendente de agendamento nem aguardando data.'}), 400

        data_jogo = payload.get('data')
        horario = payload.get('horario')
        quadra = payload.get('quadra')
        sem_data_definida = bool(payload.get('sem_data_definida')) or not data_jogo
        if not sem_data_definida and (not data_jogo or not horario or not quadra):
            return jsonify({'ok': False, 'mensagem': 'Data, horário e quadra são obrigatórios.'}), 400
        if sem_data_definida:
            partida['data'] = ''
            partida['horario'] = ''
            partida['quadra'] = ''
            partida['tipo_confronto'] = payload.get('tipo_confronto', partida.get('tipo_confronto', 'ranking_x1'))
            partida['status'] = 'aguardando_data'
            _save_partidas(data['partidas'])
            return jsonify({'ok': True, 'mensagem': 'Partida salva sem data definida.', 'partida': partida})

        horarios_validos = {h.get('hora') for h in data['horarios']}
        if horario not in horarios_validos:
            return jsonify({'ok': False, 'mensagem': f"Horário inválido. Use apenas: {', '.join(sorted(horarios_validos))}."}), 400

        conflito_q, msg_q = verificar_conflito_quadras(data['partidas'], data_jogo, horario, quadra, partida_id_ignorar=partida_id)
        if conflito_q:
            return jsonify({'ok': False, 'mensagem': msg_q}), 400

        desafiante_id = partida.get('desafiante')
        desafiado_id = partida.get('desafiado')
        conflito_d, msg_d = verificar_conflito_atleta(data['partidas'], data_jogo, horario, desafiante_id, partida_id_ignorar=partida_id)
        if conflito_d:
            return jsonify({'ok': False, 'mensagem': msg_d}), 400

        conflito_r, msg_r = verificar_conflito_atleta(data['partidas'], data_jogo, horario, desafiado_id, partida_id_ignorar=partida_id)
        if conflito_r:
            return jsonify({'ok': False, 'mensagem': msg_r}), 400

        partida['data'] = data_jogo
        partida['horario'] = horario
        partida['quadra'] = quadra
        partida['tipo_confronto'] = payload.get('tipo_confronto', partida.get('tipo_confronto', 'ranking_x1'))
        partida['status'] = 'marcada'
        _save_partidas(data['partidas'])
        return jsonify({'ok': True, 'mensagem': 'Partida agendada com sucesso.', 'partida': partida})

    @app.route('/api/secretaria/partidas/<partida_id>/remarcar', methods=['POST'])
    def api_secretaria_remarcar_partida(partida_id: str):
        _log_access('api_secretaria_remarcar_partida')
        data = _load_all()
        payload = request.get_json(silent=True) or {}

        partida = next((p for p in data['partidas'] if p.get('id') == partida_id), None)
        if not partida:
            return jsonify({'ok': False, 'mensagem': 'Partida não encontrada.'}), 404
        if partida.get('status') != 'marcada':
            return jsonify({'ok': False, 'mensagem': 'Apenas partidas marcadas podem ser remarcadas.'}), 400

        data_jogo = payload.get('data')
        horario = payload.get('horario')
        quadra = payload.get('quadra')
        sem_data_definida = bool(payload.get('sem_data_definida')) or not data_jogo

        if sem_data_definida:
            partida['data'] = ''
            partida['horario'] = ''
            partida['quadra'] = ''
            partida['tipo_confronto'] = payload.get('tipo_confronto', partida.get('tipo_confronto', 'ranking_x1'))
            partida['status'] = 'aguardando_data'
            _save_partidas(data['partidas'])
            return jsonify({'ok': True, 'mensagem': 'Partida remarcada para sem data definida.', 'partida': partida})

        horarios_validos = {h.get('hora') for h in data['horarios']}
        if horario not in horarios_validos:
            return jsonify({'ok': False, 'mensagem': f"Horário inválido. Use apenas: {', '.join(sorted(horarios_validos))}."}), 400

        conflito_q, msg_q = verificar_conflito_quadras(data['partidas'], data_jogo, horario, quadra, partida_id_ignorar=partida_id)
        if conflito_q:
            return jsonify({'ok': False, 'mensagem': msg_q}), 400

        desafiante_id = partida.get('desafiante')
        desafiado_id = partida.get('desafiado')
        conflito_d, msg_d = verificar_conflito_atleta(data['partidas'], data_jogo, horario, desafiante_id, partida_id_ignorar=partida_id)
        if conflito_d:
            return jsonify({'ok': False, 'mensagem': msg_d}), 400

        conflito_r, msg_r = verificar_conflito_atleta(data['partidas'], data_jogo, horario, desafiado_id, partida_id_ignorar=partida_id)
        if conflito_r:
            return jsonify({'ok': False, 'mensagem': msg_r}), 400

        partida['data'] = data_jogo
        partida['horario'] = horario
        partida['quadra'] = quadra
        partida['tipo_confronto'] = payload.get('tipo_confronto', partida.get('tipo_confronto', 'ranking_x1'))
        partida['status'] = 'marcada'
        partida['remarcada_em'] = agora_brasilia().isoformat(timespec='minutes')
        _save_partidas(data['partidas'])
        return jsonify({'ok': True, 'mensagem': 'Partida remarcada com sucesso.', 'partida': partida})

    @app.route('/api/partidas/<partida_id>', methods=['DELETE'])
    def api_excluir_partida(partida_id: str):
        data = _load_all()
        partidas = data['partidas']
        partida = next((p for p in partidas if p.get('id') == partida_id), None)
        if partida is None:
            return jsonify({'ok': False, 'mensagem': 'Partida não encontrada.'}), 404
        if partida.get('status') == 'cancelada':
            return jsonify({'ok': False, 'mensagem': 'Partida já está cancelada.'}), 400
        partida['status_anterior'] = partida.get('status', 'marcada')
        partida['status'] = 'cancelada'
        partida['cancelada_em'] = agora_brasilia().isoformat(timespec='minutes')
        _save_partidas(partidas)
        return jsonify({'ok': True, 'mensagem': 'Partida cancelada. Você pode desfazer.', 'partida': partida})

    @app.route('/api/partidas/<partida_id>/restaurar', methods=['POST'])
    def api_restaurar_partida(partida_id: str):
        data = _load_all()
        partidas = data['partidas']
        partida = next((p for p in partidas if p.get('id') == partida_id), None)
        if partida is None:
            return jsonify({'ok': False, 'mensagem': 'Partida não encontrada.'}), 404
        if partida.get('status') != 'cancelada':
            return jsonify({'ok': False, 'mensagem': 'Apenas partidas canceladas podem ser restauradas.'}), 400
        partida['status'] = partida.get('status_anterior', 'marcada')
        partida.pop('status_anterior', None)
        partida.pop('cancelada_em', None)
        _save_partidas(partidas)
        return jsonify({'ok': True, 'mensagem': 'Exclusão desfeita com sucesso.', 'partida': partida})

    @app.route('/api/registrar-resultado', methods=['POST'])
    def api_registrar_resultado():
        _log_access('api_registrar_resultado')
        data = _load_all()
        payload = request.get_json(silent=True) or {}

        partida = next((p for p in data['partidas'] if p.get('id') == payload.get('partida_id')), None)
        if not partida:
            return jsonify({'ok': False, 'mensagem': 'Partida não encontrada.'}), 404
        if not _actor_can_manage_partida(partida):
            return jsonify({'ok': False, 'mensagem': 'Você só pode lançar resultado de partidas em que esteja envolvido.'}), 403

        if partida.get('status') not in {'marcada', 'em_andamento'}:
            return jsonify({'ok': False, 'mensagem': 'Partida não está disponível para registro.'}), 400

        # Resultado deve ser lançado até 23:59 do dia da partida.
        limite = datetime.strptime(f"{partida['data']} 23:59", '%Y-%m-%d %H:%M')
        if agora_brasilia() > limite:
            partida['status'] = 'desconsiderada'
            _save_partidas(data['partidas'])
            return jsonify({'ok': False, 'mensagem': 'Prazo expirado. Partida desconsiderada por regulamento.'}), 400

        vencedor_id = payload.get('vencedor')
        if vencedor_id not in {partida.get('desafiante'), partida.get('desafiado')}:
            return jsonify({'ok': False, 'mensagem': 'O vencedor informado não pertence a esta partida.'}), 400

        try:
            partida['resultado'] = formatar_placar_por_ordem_da_partida(
                payload.get('placar', ''),
                inverter_sets=(vencedor_id == partida.get('desafiado')),
            )
        except ValueError as exc:
            return jsonify({'ok': False, 'mensagem': str(exc)}), 400
        partida['vencedor'] = vencedor_id
        partida['wo'] = bool(payload.get('wo', False))
        partida['observacoes'] = payload.get('observacoes', partida.get('observacoes', ''))
        partida['status_antes_resultado'] = partida.get('status', 'marcada')

        # Snapshot para permitir apagar resultado com reversão segura do ranking.
        ranking_partida = partida.get('categoria')
        snapshot = {}
        for a in data['atletas']:
            if a.get('ranking') == ranking_partida:
                snapshot[a['id']] = {
                    'posicao': a.get('posicao'),
                    'wo_consecutivos': a.get('wo_consecutivos'),
                    'ultimo_jogo': a.get('ultimo_jogo'),
                    'ultimo_desafio': a.get('ultimo_desafio'),
                    'bloqueado_ate': a.get('bloqueado_ate'),
                    'observacoes': a.get('observacoes'),
                }
        partida['snapshot_pre_resultado'] = snapshot

        ok, msg = atualizar_ranking_apos_resultado(partida, data['atletas'])
        if not ok:
            return jsonify({'ok': False, 'mensagem': msg}), 400

        _save_atletas(data['atletas'])
        _save_partidas(data['partidas'])
        return jsonify({'ok': True, 'mensagem': msg, 'partida': partida})

    @app.route('/api/apagar-resultado/<partida_id>', methods=['DELETE'])
    def api_apagar_resultado(partida_id: str):
        _log_access('api_apagar_resultado')
        data = _load_all()
        partida = next((p for p in data['partidas'] if p.get('id') == partida_id), None)
        if not partida:
            return jsonify({'ok': False, 'mensagem': 'Partida não encontrada.'}), 404
        if not _actor_can_manage_partida(partida):
            return jsonify({'ok': False, 'mensagem': 'Você só pode apagar resultados de partidas em que esteja envolvido.'}), 403

        ok, msg = reverter_resultado_com_snapshot(partida, data['atletas'])
        if not ok:
            return jsonify({'ok': False, 'mensagem': msg}), 400

        _save_atletas(data['atletas'])
        _save_partidas(data['partidas'])
        return jsonify({'ok': True, 'mensagem': msg, 'partida': partida})

    @app.route('/api/secretaria/partidas/<partida_id>/reativar-desconsiderada', methods=['POST'])
    def api_secretaria_reativar_desconsiderada(partida_id: str):
        _log_access('api_secretaria_reativar_desconsiderada')
        data = _load_all()
        partida = next((p for p in data['partidas'] if p.get('id') == partida_id), None)
        if not partida:
            return jsonify({'ok': False, 'mensagem': 'Partida não encontrada.'}), 404
        if partida.get('status') != 'desconsiderada':
            return jsonify({'ok': False, 'mensagem': 'Apenas partidas desconsideradas podem ser reativadas.'}), 400

        partida['status'] = partida.get('status_antes_resultado', 'marcada')
        partida['resultado'] = None
        partida['vencedor'] = None
        partida['wo'] = False
        partida['data_registro_resultado'] = None
        partida['observacoes'] = partida.get('observacoes', '')
        partida['reativada_em'] = agora_brasilia().isoformat(timespec='minutes')
        partida.pop('status_antes_resultado', None)
        partida.pop('snapshot_pre_resultado', None)

        _save_partidas(data['partidas'])
        return jsonify({'ok': True, 'mensagem': 'Partida reativada para novo lançamento de resultado.', 'partida': partida})

    @app.route('/api/secretaria/status-atleta', methods=['POST'])
    def api_secretaria_status():
        _log_access('api_secretaria_status')
        data = _load_all()
        payload = request.get_json(silent=True) or {}
        atleta = next((a for a in data['atletas'] if a.get('id') == payload.get('atleta_id')), None)
        if not atleta:
            return jsonify({'ok': False, 'mensagem': 'Atleta não encontrado.'}), 404

        # Atualizacoes administrativas simples.
        if 'ativo' in payload:
            atleta['ativo'] = bool(payload['ativo'])
        if 'neutro' in payload:
            atleta['neutro'] = bool(payload['neutro'])
        if 'retirado' in payload:
            atleta['retirado'] = bool(payload['retirado'])
            if atleta['retirado']:
                atleta['ativo'] = False
                atleta['observacoes'] = payload.get('observacoes') or atleta.get('observacoes') or 'Atleta retirado do ranking.'
        if 'status_financeiro' in payload:
            atleta['status_financeiro'] = payload['status_financeiro']
        if 'bloqueio_secretaria' in payload:
            atleta['bloqueio_secretaria'] = bool(payload['bloqueio_secretaria'])
            if not atleta['bloqueio_secretaria']:
                atleta['bloqueio_motivo'] = ''
        if 'bloqueio_motivo' in payload:
            atleta['bloqueio_motivo'] = payload['bloqueio_motivo']
        if 'observacoes' in payload:
            atleta['observacoes'] = payload['observacoes']

        normalizar_posicoes_ranking(data['atletas'], atleta.get('ranking'))
        _recalcular_classes_ranking(data['atletas'], atleta.get('ranking'))
        _save_atletas(data['atletas'])
        return jsonify({'ok': True, 'mensagem': 'Status atualizado com sucesso.', 'atleta': atleta})

    @app.route('/api/secretaria/trocar-posicoes', methods=['POST'])
    def api_secretaria_trocar_posicoes():
        _log_access('api_secretaria_trocar_posicoes')
        data = _load_all()
        payload = request.get_json(silent=True) or {}

        atleta_a = next((a for a in data['atletas'] if a.get('id') == payload.get('atleta_a_id')), None)
        atleta_b = next((a for a in data['atletas'] if a.get('id') == payload.get('atleta_b_id')), None)

        if not atleta_a or not atleta_b:
            return jsonify({'ok': False, 'mensagem': 'Selecione dois atletas válidos.'}), 404
        if atleta_a.get('id') == atleta_b.get('id'):
            return jsonify({'ok': False, 'mensagem': 'Selecione atletas diferentes para a troca.'}), 400
        if atleta_a.get('ranking') != atleta_b.get('ranking'):
            return jsonify({'ok': False, 'mensagem': 'A troca manual só pode ocorrer dentro do mesmo ranking.'}), 400
        if atleta_a.get('retirado') or atleta_b.get('retirado') or not atleta_a.get('ativo') or not atleta_b.get('ativo'):
            return jsonify({'ok': False, 'mensagem': 'A troca só pode ocorrer entre atletas ativos do ranking.'}), 400
        pos_a = int(atleta_a.get('posicao', 0) or 0)
        pos_b = int(atleta_b.get('posicao', 0) or 0)
        if pos_a <= 0 or pos_b <= 0:
            return jsonify({'ok': False, 'mensagem': 'Posições inválidas para a troca manual.'}), 400
        if pos_a <= pos_b:
            return jsonify({
                'ok': False,
                'mensagem': 'Para este ajuste, o Atleta 1 deve estar abaixo do Atleta 2 na tabela.',
            }), 400

        ranking = atleta_a.get('ranking')
        atletas_mesmo_ranking = [
            atleta for atleta in data['atletas']
            if atleta.get('ranking') == ranking and atleta.get('ativo') and not atleta.get('retirado')
        ]
        for atleta in atletas_mesmo_ranking:
            posicao = int(atleta.get('posicao', 0) or 0)
            if pos_b <= posicao < pos_a:
                atleta['posicao'] = posicao + 1
        atleta_a['posicao'] = pos_b

        normalizar_posicoes_ranking(data['atletas'], atleta_a.get('ranking'))
        _recalcular_classes_ranking(data['atletas'], atleta_a.get('ranking'))
        _save_atletas(data['atletas'])

        return jsonify({
            'ok': True,
            'mensagem': f"{atleta_a.get('nome')} assumiu a posição de {atleta_b.get('nome')}, com ajuste do intervalo.",
            'atletas': [atleta_a, atleta_b],
        })

    return app


app = create_app()


if __name__ == '__main__':
    port = int(os.getenv('PORT', '5005'))
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
