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
    verificar_conflito_atleta,
    verificar_conflito_quadras,
)
from ranking_logic import atualizar_ranking_apos_resultado
from regras_ranking import listar_desafios_possiveis, pode_desafiar, verificar_status_atleta
from utils import carregar_json, formatar_status, gerar_id_partida, indice_por_id, ordenar_partidas_por_data, salvar_json

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
        if p.get('status') in {'finalizada', 'realizada'}
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
        desafios = listar_desafios_possiveis(atleta, atletas, partidas=partidas)
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
        data = _load_all()
        atletas = data['atletas']
        partidas = data['partidas']
        atleta = next((a for a in atletas if a['id'] == atleta_id), None)
        if not atleta:
            return jsonify({'erro': 'Atleta não encontrado'}), 404
        return jsonify(listar_desafios_possiveis(atleta, atletas, partidas=partidas))

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

    @app.route('/api/desafio/registrar', methods=['POST'])
    def api_registrar_desafio_para_secretaria():
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

        valido, motivo = pode_desafiar(desafiante, desafiado)
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
