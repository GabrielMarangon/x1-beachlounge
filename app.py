from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template, request

from agenda import (
    agendar_partida,
    listar_horarios_disponiveis,
    listar_partidas_marcadas,
    listar_partidas_por_atleta,
    listar_partidas_por_data,
)
from ranking_logic import atualizar_ranking_apos_resultado
from regras_ranking import listar_desafios_possiveis, pode_desafiar, verificar_status_atleta
from utils import carregar_json, formatar_status, indice_por_id, ordenar_partidas_por_data, salvar_json

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'dados'
ATLETAS_PATH = DATA_DIR / 'atletas.json'
QUADRAS_PATH = DATA_DIR / 'quadras.json'
HORARIOS_PATH = DATA_DIR / 'horarios.json'
PARTIDAS_PATH = DATA_DIR / 'partidas.json'

RANKING_ROTULOS = {
    'masculino_principal': 'Masculino Principal',
    'feminina_iniciantes': 'Feminina Iniciantes',
    'infantil_a': 'Infantil A',
}


def _load_all() -> Dict[str, Any]:
    return {
        'atletas': carregar_json(ATLETAS_PATH),
        'quadras': carregar_json(QUADRAS_PATH),
        'horarios': carregar_json(HORARIOS_PATH),
        'partidas': carregar_json(PARTIDAS_PATH),
    }


def _save_atletas(atletas: List[Dict[str, Any]]) -> None:
    salvar_json(ATLETAS_PATH, atletas)


def _save_partidas(partidas: List[Dict[str, Any]]) -> None:
    salvar_json(PARTIDAS_PATH, partidas)


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
        por_categoria[rk] = len([a for a in atletas if a.get('ranking') == rk and a.get('ativo') and not a.get('retirado')])

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
        if p.get('status') == 'finalizada'
    ]
    ultimos_resultados = sorted(
        ultimos_resultados,
        key=lambda p: f"{p.get('data', '')} {p.get('horario', '')}",
        reverse=True,
    )[:5]

    top5_masculino = sorted(
        [
            a for a in atletas
            if a.get('ranking') == 'masculino_principal' and a.get('ativo') and not a.get('retirado')
        ],
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
        if not participa or p.get('status') != 'finalizada':
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

    @app.route('/')
    def index():
        data = _load_all()
        return render_template('index.html', resumo=_resumo_home(data), ranking_rotulos=RANKING_ROTULOS)

    @app.route('/ranking')
    def ranking_page():
        return render_template('ranking.html', ranking_rotulos=RANKING_ROTULOS)

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

    @app.route('/secretaria')
    def secretaria_page():
        return render_template('secretaria.html', ranking_rotulos=RANKING_ROTULOS)

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
        atletas = data['atletas']

        if ranking:
            atletas = [a for a in atletas if a.get('ranking') == ranking]

        atletas = sorted(atletas, key=lambda x: (x.get('ranking', ''), int(x.get('posicao', 999))))
        for a in atletas:
            a['status_visual'] = formatar_status(a)
        return jsonify(atletas)

    @app.route('/api/atletas')
    def api_atletas():
        data = _load_all()
        atletas = data['atletas']
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
        desafios = listar_desafios_possiveis(atleta, atletas)
        pode_ser_desafiado_por = []
        for cand in atletas:
            if cand['id'] == atleta_id:
                continue
            v, _ = pode_desafiar(cand, atleta)
            if v:
                pode_ser_desafiado_por.append({'id': cand['id'], 'nome': cand['nome'], 'posicao': cand['posicao']})

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
        atletas = _load_all()['atletas']
        atleta = next((a for a in atletas if a['id'] == atleta_id), None)
        if not atleta:
            return jsonify({'erro': 'Atleta não encontrado'}), 404
        return jsonify(listar_desafios_possiveis(atleta, atletas))

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
        historico = [p for p in partidas_atleta if p.get('status') == 'finalizada']

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

    @app.route('/api/partidas/<partida_id>', methods=['DELETE'])
    def api_excluir_partida(partida_id: str):
        data = _load_all()
        partidas = data['partidas']
        idx = next((i for i, p in enumerate(partidas) if p.get('id') == partida_id), None)
        if idx is None:
            return jsonify({'ok': False, 'mensagem': 'Partida não encontrada.'}), 404
        removida = partidas.pop(idx)
        _save_partidas(partidas)
        return jsonify({'ok': True, 'mensagem': 'Partida excluída com sucesso.', 'partida': removida})

    @app.route('/api/registrar-resultado', methods=['POST'])
    def api_registrar_resultado():
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

        partida['resultado'] = payload.get('placar')
        partida['vencedor'] = payload.get('vencedor')
        partida['wo'] = bool(payload.get('wo', False))
        partida['observacoes'] = payload.get('observacoes', partida.get('observacoes', ''))

        ok, msg = atualizar_ranking_apos_resultado(partida, data['atletas'])
        if not ok:
            return jsonify({'ok': False, 'mensagem': msg}), 400

        _save_atletas(data['atletas'])
        _save_partidas(data['partidas'])
        return jsonify({'ok': True, 'mensagem': msg, 'partida': partida})

    @app.route('/api/secretaria/status-atleta', methods=['POST'])
    def api_secretaria_status():
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

        _save_atletas(data['atletas'])
        return jsonify({'ok': True, 'mensagem': 'Status atualizado com sucesso.', 'atleta': atleta})

    return app


app = create_app()


if __name__ == '__main__':
    port = int(os.getenv('PORT', '5004'))
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
