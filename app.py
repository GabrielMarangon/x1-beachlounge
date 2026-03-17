from __future__ import annotations

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
from ranking_logic import atualizar_ranking_apos_resultado
from regras_ranking import listar_desafios_possiveis, pode_desafiar_com_partidas, verificar_status_atleta
from utils import (
    atletas_ativos_do_ranking,
    formatar_placar_por_ordem_da_partida,
    formatar_status,
    gerar_id_partida,
    indice_por_id,
    normalizar_posicoes_ranking,
    ordenar_partidas_por_data,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'dados'


def _runtime_data_dir() -> Path:
    configured = os.getenv('X1_BTC_DATA_DIR') or os.getenv('RENDER_DISK_PATH')
    if configured:
        return Path(configured)
    default_render_disk = Path('/var/data')
    if os.name != 'nt' and default_render_disk.exists():
        return default_render_disk
    return DATA_DIR


RUNTIME_DATA_DIR = _runtime_data_dir()
ATLETAS_PATH = DATA_DIR / 'atletas.json'
QUADRAS_PATH = DATA_DIR / 'quadras.json'
HORARIOS_PATH = DATA_DIR / 'horarios.json'
PARTIDAS_PATH = DATA_DIR / 'partidas.json'
DB_PATH = RUNTIME_DATA_DIR / 'x1_btc.db'
STORE = DataStore(DB_PATH, DATA_DIR, RUNTIME_DATA_DIR)

RANKING_ROTULOS = {
    'masculino_principal': 'Masculino Principal',
    'feminina_iniciantes': 'Feminina Iniciantes',
    'infantil_a': 'Infantil A',
}
SECRETARIA_USERNAME = os.getenv('SECRETARIA_USERNAME', '').strip()
SECRETARIA_PASSWORD_HASH = os.getenv('SECRETARIA_PASSWORD_HASH', '').strip()
SECRETARIA_PASSWORD = os.getenv('SECRETARIA_PASSWORD', '').strip()
ACCESS_LOG_LIMIT = 2000
SEED_PARTIDAS_ASSINATURAS = {
    ('p001', 'masculino_principal_gabriel_marangon', 'masculino_principal_oscar', '2026-03-18', '19:00', 'quadra_1'),
    ('p002', 'infantil_a_pedro_crespo', 'infantil_a_benjamin', '2026-03-19', '18:00', 'quadra_2'),
    ('p003', 'feminina_iniciantes_micheli', 'feminina_iniciantes_daiane', '2026-03-20', '20:00', 'quadra_3'),
    ('p004', 'masculino_principal_gabriel_marangon', 'masculino_principal_oscar', '2026-03-17', '18:00', 'quadra_1'),
}


def _eh_partida_seed(partida: Dict[str, Any]) -> bool:
    assinatura = (
        partida.get('id'),
        partida.get('desafiante'),
        partida.get('desafiado'),
        partida.get('data'),
        partida.get('horario'),
        partida.get('quadra'),
    )
    return (
        assinatura in SEED_PARTIDAS_ASSINATURAS
        and partida.get('status') == 'marcada'
        and not partida.get('resultado')
        and not partida.get('data_registro_resultado')
    )


def _load_all() -> Dict[str, Any]:
    data = {
        'atletas': STORE.load_dataset('atletas'),
        'quadras': STORE.load_dataset('quadras'),
        'horarios': STORE.load_dataset('horarios'),
        'partidas': STORE.load_dataset('partidas'),
    }
    partidas_sem_seed = [partida for partida in data['partidas'] if not _eh_partida_seed(partida)]
    if len(partidas_sem_seed) != len(data['partidas']):
        data['partidas'] = partidas_sem_seed
        _save_partidas(data['partidas'])
    normalizar_posicoes_ranking(data['atletas'])
    return data


def _save_atletas(atletas: List[Dict[str, Any]]) -> None:
    STORE.save_dataset('atletas', atletas)


def _save_partidas(partidas: List[Dict[str, Any]]) -> None:
    STORE.save_dataset('partidas', partidas)


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
        'nome': session.get('visitante_nome', '').strip(),
        'contato': session.get('visitante_contato', '').strip(),
        'tipo': 'secretaria' if session.get('secretaria_autorizada') else 'visitante',
    }


def _log_access(evento: str) -> None:
    if request.endpoint == 'health' or request.path.startswith('/static/'):
        return

    logs = _load_access_logs()
    visitante = _visitor_identity()
    logs.append({
        'timestamp': datetime.now().isoformat(timespec='seconds'),
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

    if ranking == 'masculino_principal':
        ativos_ordenados = sorted(
            [a for a in atletas if a.get('ranking') == ranking and a.get('ativo') and not a.get('retirado')],
            key=lambda item: int(item.get('posicao', 9999) or 9999),
        )
        for atleta in ativos_ordenados:
            atleta['classe'] = _classe_por_ranking_posicao(ranking, int(atleta.get('posicao', 0) or 0))

    return atleta_novo


def _candidatos_que_podem_desafiar(atleta: Dict[str, Any], atletas: List[Dict[str, Any]], partidas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranking = atleta.get('ranking')
    posicao = int(atleta.get('posicao', 0) or 0)
    candidatos = [
        cand for cand in atletas
        if cand.get('id') != atleta.get('id')
        and cand.get('ranking') == ranking
        and cand.get('ativo')
        and not cand.get('retirado')
        and int(cand.get('posicao', 0) or 0) > posicao
        and (int(cand.get('posicao', 0) or 0) - posicao) <= 3
    ]

    saida = []
    for cand in sorted(candidatos, key=lambda item: int(item.get('posicao', 999))):
        valido, motivo = pode_desafiar_com_partidas(cand, atleta, partidas)
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
    if ranking != 'masculino_principal':
        return
    for atleta in atletas:
        if atleta.get('ranking') == ranking and atleta.get('ativo') and not atleta.get('retirado'):
            atleta['classe'] = _classe_por_ranking_posicao(ranking, int(atleta.get('posicao', 0) or 0))


def _resumo_home(data: Dict[str, Any]) -> Dict[str, Any]:
    partidas = data['partidas']
    atletas = data['atletas']
    quadras = data['quadras']
    hoje = datetime.now().strftime('%Y-%m-%d')

    atletas_map = indice_por_id(atletas)
    quadras_map = indice_por_id(quadras)

    jogos_hoje_base = [p for p in partidas if p.get('data') == hoje and p.get('status') == 'marcada']
    jogos_hoje = [_enriquecer_partida(p, atletas_map, quadras_map) for p in jogos_hoje_base]
    jogos_hoje = sorted(jogos_hoje, key=lambda x: x.get('horario', '99:99'))

    pendentes_resultado = [p for p in partidas if p.get('status') == 'marcada' and datetime.strptime(p['data'], '%Y-%m-%d') < datetime.now()]
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


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv('FLASK_SECRET_KEY') or os.getenv('SECRET_KEY') or 'x1-btc-dev-key'

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

        if request.method == 'GET' and not request.path.startswith('/api/'):
            _log_access('pagina')
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
        return render_template('agenda.html')

    @app.route('/atleta/<atleta_id>')
    def atleta_page(atleta_id: str):
        return render_template('atleta.html', atleta_id=atleta_id)

    @app.route('/partidas')
    def partidas_page():
        return render_template('partidas.html', ranking_rotulos=RANKING_ROTULOS)

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
        return render_template(
            'secretaria.html',
            ranking_rotulos=RANKING_ROTULOS,
            secretaria_usuario=session.get('secretaria_usuario', ''),
        )

    @app.route('/desafio')
    def desafio_page():
        return render_template('desafio.html')

    @app.route('/health')
    def health():
        return {'status': 'ok'}, 200

    @app.route('/api/ranking')
    def api_ranking():
        data = _load_all()
        ranking = request.args.get('ranking')
        atletas = [atleta.copy() for atleta in data['atletas'] if not atleta.get('retirado')]

        if ranking:
            atletas = [a for a in atletas if a.get('ranking') == ranking]

        atletas = sorted(atletas, key=lambda x: (x.get('ranking', ''), int(x.get('posicao', 999))))
        for a in atletas:
            a['status_visual'] = formatar_status(a)
        return jsonify(atletas)

    @app.route('/api/atletas')
    def api_atletas():
        data = _load_all()
        atletas = [atleta.copy() for atleta in data['atletas']]
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
            'atleta': atleta,
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
        data_ref = request.args.get('data') or datetime.now().strftime('%Y-%m-%d')
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
            'atleta': atleta,
            'lancaveis': lancaveis,
            'historico': historico,
            'estatisticas': _estatisticas_atleta(atleta_id, data['partidas']),
        })

    @app.route('/api/agendar', methods=['POST'])
    def api_agendar():
        data = _load_all()
        payload = request.get_json(silent=True) or {}
        horarios_validos = {h.get('hora') for h in data['horarios']}
        if payload.get('horario') not in horarios_validos:
            return jsonify({
                'ok': False,
                'mensagem': f"Horário inválido. Use apenas: {', '.join(sorted(horarios_validos))}.",
            }), 400
        ok, msg, partida = agendar_partida(data['atletas'], data['partidas'], payload)
        if not ok:
            return jsonify({'ok': False, 'mensagem': msg}), 400
        _save_partidas(data['partidas'])
        return jsonify({'ok': True, 'mensagem': msg, 'partida': partida})

    @app.route('/api/secretaria/desafios-pendentes')
    def api_desafios_pendentes_secretaria():
        data = _load_all()
        atletas_map = indice_por_id(data['atletas'])
        quadras_map = indice_por_id(data['quadras'])
        pendentes = [
            _enriquecer_partida(p, atletas_map, quadras_map)
            for p in data['partidas']
            if p.get('status') == 'pendente_agendamento'
        ]
        pendentes = sorted(pendentes, key=lambda p: p.get('data_desafio', ''), reverse=True)
        return jsonify(pendentes)

    @app.route('/api/secretaria/acessos')
    def api_secretaria_acessos():
        logs = sorted(_load_access_logs(), key=lambda item: item.get('timestamp', ''), reverse=True)
        return jsonify(logs[:200])

    @app.route('/api/secretaria/atletas', methods=['POST'])
    def api_secretaria_inserir_atleta():
        _log_access('api_secretaria_inserir_atleta')
        data = _load_all()
        payload = request.get_json(silent=True) or {}

        nome = (payload.get('nome') or '').strip()
        ranking = (payload.get('ranking') or '').strip()
        if not nome:
            return jsonify({'ok': False, 'mensagem': 'Informe o nome do atleta.'}), 400
        if ranking not in RANKING_ROTULOS:
            return jsonify({'ok': False, 'mensagem': 'Categoria de ranking inválida.'}), 400

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

    @app.route('/api/desafio/registrar', methods=['POST'])
    def api_registrar_desafio_para_secretaria():
        _log_access('api_secretaria_desafio_registrar')
        data = _load_all()
        payload = request.get_json(silent=True) or {}
        desafiante_id = payload.get('desafiante_id')
        desafiado_id = payload.get('desafiado_id')
        if not desafiante_id or not desafiado_id:
            return jsonify({'ok': False, 'mensagem': 'Desafiante e desafiado são obrigatórios.'}), 400

        atletas = data['atletas']
        desafiante = next((a for a in atletas if a.get('id') == desafiante_id), None)
        desafiado = next((a for a in atletas if a.get('id') == desafiado_id), None)
        if not desafiante or not desafiado:
            return jsonify({'ok': False, 'mensagem': 'Atletas não encontrados.'}), 404

        valido, motivo = pode_desafiar_com_partidas(desafiante, desafiado, data['partidas'])
        if not valido:
            return jsonify({'ok': False, 'mensagem': motivo}), 400

        existente = next(
            (
                p for p in data['partidas']
                if p.get('status') in {'pendente_agendamento', 'marcada', 'em_andamento'}
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
            'data_desafio': datetime.now().isoformat(timespec='minutes'),
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
        if partida.get('status') != 'pendente_agendamento':
            return jsonify({'ok': False, 'mensagem': 'Partida não está pendente de agendamento.'}), 400

        data_jogo = payload.get('data')
        horario = payload.get('horario')
        quadra = payload.get('quadra')
        if not data_jogo or not horario or not quadra:
            return jsonify({'ok': False, 'mensagem': 'Data, horário e quadra são obrigatórios.'}), 400

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
        partida['cancelada_em'] = datetime.now().isoformat(timespec='minutes')
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

        if partida.get('status') not in {'marcada', 'em_andamento'}:
            return jsonify({'ok': False, 'mensagem': 'Partida não está disponível para registro.'}), 400

        # Resultado deve ser lançado até 23:59 do dia da partida.
        limite = datetime.strptime(f"{partida['data']} 23:59", '%Y-%m-%d %H:%M')
        if datetime.now() > limite:
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

        if partida.get('status') not in {'finalizada', 'realizada'}:
            return jsonify({'ok': False, 'mensagem': 'Somente partidas com resultado lançado podem ser apagadas.'}), 400

        snapshot = partida.get('snapshot_pre_resultado')
        if not isinstance(snapshot, dict) or not snapshot:
            return jsonify({
                'ok': False,
                'mensagem': 'Não foi possível reverter automaticamente este resultado (snapshot ausente).',
            }), 400

        atletas_map = indice_por_id(data['atletas'])
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

        normalizar_posicoes_ranking(data['atletas'], partida.get('categoria'))

        partida['status'] = partida.get('status_antes_resultado', 'marcada')
        partida['resultado'] = None
        partida['vencedor'] = None
        partida['wo'] = False
        partida['data_registro_resultado'] = None
        partida['resultado_apagado_em'] = datetime.now().isoformat(timespec='minutes')
        partida.pop('snapshot_pre_resultado', None)
        partida.pop('status_antes_resultado', None)

        _save_atletas(data['atletas'])
        _save_partidas(data['partidas'])
        return jsonify({'ok': True, 'mensagem': 'Resultado apagado e ranking revertido com sucesso.', 'partida': partida})

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

    return app


app = create_app()


if __name__ == '__main__':
    port = int(os.getenv('PORT', '5004'))
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
