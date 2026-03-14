async function api(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.mensagem || data.erro || 'Falha na requisição');
  return data;
}

function statusClass(cor) {
  return cor ? `status-${cor}` : 'status-cinza';
}

function setMsg(id, txt, ok = true) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = txt;
  el.style.color = ok ? '#1f6b46' : '#a33131';
}

function aplicarFallbackLogos() {
  const fallbacks = ['/static/images/logo_btc.svg', '/static/images/logo_ranking_x1.svg'];
  const aplicar = (img, index) => {
    img.src = fallbacks[index] || fallbacks[0];
  };
  document.querySelectorAll('.brand-logo').forEach((img, index) => {
    img.addEventListener('error', () => {
      aplicar(img, index);
    }, { once: true });
    // Se já falhou antes do bind do evento, aplica fallback direto.
    if (img.complete && img.naturalWidth === 0) {
      aplicar(img, index);
    }
  });
}

function destacarMenuAtivo() {
  const path = window.location.pathname;
  document.querySelectorAll('.nav-links a').forEach((a) => {
    const href = a.getAttribute('href');
    if (href === path) a.classList.add('active');
  });
}

let partidasLancaveisAtleta = [];
let nomeAtletaSelecionadoDesafio = '';
let rankingAtualCache = [];

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function statusDesafioVisual(item) {
  if (item.pode_desafiar) return { cls: 'desafio-apto', label: 'Apto ✅' };
  return { cls: 'desafio-bloqueado', label: 'Bloqueado 🚫' };
}

function montarTextoRanking() {
  const select = document.getElementById('filtroRanking');
  const categoria = select?.selectedOptions?.[0]?.textContent || 'Ranking';
  const linhas = [
    `RANKING BTC 2026 - ${categoria}`,
    '',
    ...rankingAtualCache.map((atleta) => `${atleta.posicao}. ${atleta.nome} (${atleta.classe || 'Sem classe'})`),
  ];
  return linhas.join('\n');
}

async function enviarDesafioParaSecretaria(desafianteId, desafiadoId) {
  if (!desafianteId || !desafiadoId) return;
  try {
    const out = await api('/api/desafio/registrar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        desafiante_id: desafianteId,
        desafiado_id: desafiadoId,
      }),
    });
    setMsg('msgCopiarQuadro', out.mensagem || 'Desafio enviado para a secretaria.', true);
  } catch (err) {
    setMsg('msgCopiarQuadro', err.message || 'Falha ao enviar desafio para a secretaria.', false);
  }
}

async function copiarQuadroDesafio() {
  const desafio = document.getElementById('qDesafio')?.textContent?.trim() || 'NOME DO DESAFIANTE x NOME DO DESAFIADO';
  const limite = document.getElementById('qLimite')?.textContent?.trim() || 'DE = ___ ATÉ = ___';
  const dia = document.getElementById('qDia')?.textContent?.trim() || '___';
  const hora = document.getElementById('qHora')?.textContent?.trim() || '___';

  const texto = [
    'RANKING BTC 2026',
    '',
    `⌛ DESAFIOS: ${desafio}`,
    '',
    `DATA LIMITE= ${limite}`,
    '',
    '🎾 DATA E HORÁRIO MARCADO',
    `⌛ Dia: ${dia}`,
    `⏰ Horário: ${hora}`,
  ].join('\n');

  try {
    await navigator.clipboard.writeText(texto);
    setMsg('msgCopiarQuadro', 'Quadro copiado com sucesso.');
  } catch (err) {
    setMsg('msgCopiarQuadro', 'Não foi possível copiar automaticamente. Copie manualmente.', false);
  }
}

async function carregarRanking() {
  const select = document.getElementById('filtroRanking');
  const tbody = document.querySelector('#rankingTable tbody');
  if (!select || !tbody) return;

  const ranking = select.value;
  const atletas = await api(`/api/ranking?ranking=${ranking}`);
  rankingAtualCache = atletas;
  tbody.innerHTML = atletas.map(a => `
    <tr>
      <td>${a.posicao}</td>
      <td><a href="/atleta/${a.id}">${a.nome}</a></td>
      <td>${a.classe || '-'}</td>
      <td><span class="status-chip ${statusClass(a.status_visual?.cor)}">${a.status_visual?.label || '-'}</span></td>
    </tr>
  `).join('');
}

async function copiarRanking() {
  const texto = montarTextoRanking();
  if (!rankingAtualCache.length) {
    setMsg('msgRankingShare', 'Nenhum ranking carregado para copiar.', false);
    return;
  }
  try {
    await navigator.clipboard.writeText(texto);
    setMsg('msgRankingShare', 'Lista do ranking copiada.');
  } catch (err) {
    setMsg('msgRankingShare', 'Falha ao copiar a lista do ranking.', false);
  }
}

function compartilharRankingWhatsapp() {
  const texto = montarTextoRanking();
  if (!rankingAtualCache.length) {
    setMsg('msgRankingShare', 'Nenhum ranking carregado para compartilhar.', false);
    return;
  }
  const url = `https://wa.me/?text=${encodeURIComponent(texto)}`;
  window.open(url, '_blank', 'noopener');
  setMsg('msgRankingShare', 'WhatsApp aberto com a lista pronta para envio.');
}

async function carregarAgenda() {
  const dataInput = document.getElementById('agendaData');
  const tbody = document.querySelector('#agendaTable tbody');
  if (!dataInput || !tbody) return;

  const data = dataInput.value;
  const slots = await api(`/api/agenda?data=${data}`);
  const partidasDia = await api(`/api/partidas?data=${data}`);
  const horarios = [...new Set(slots.map(s => s.horario))].sort();
  const quadras = [...new Set(slots.map(s => s.quadra_nome))].sort();

  const head = document.querySelector('#agendaTable thead tr');
  if (head && quadras.length) {
    head.innerHTML = `<th>Horário</th>${quadras.map(q => `<th>${q}</th>`).join('')}`;
  }

  const mapaSlots = new Map();
  slots.forEach((s) => mapaSlots.set(`${s.horario}__${s.quadra_nome}`, s));

  const mapaPartidas = new Map();
  partidasDia
    .filter((p) => p.status === 'marcada' || p.status === 'em_andamento')
    .forEach((p) => mapaPartidas.set(`${p.horario}__${p.quadra_nome}`, p));

  tbody.innerHTML = horarios.map((h) => {
    const cols = quadras.map((q) => {
      const key = `${h}__${q}`;
      const partida = mapaPartidas.get(key);
      const slot = mapaSlots.get(key);

      if (partida) {
        return `<td><div class="agenda-cell agenda-ocupada"><strong>Jogo marcado</strong><span class="mini">${partida.desafiante_nome} x ${partida.desafiado_nome}</span></div></td>`;
      }
      if (slot && slot.livre) {
        return '<td><div class="agenda-cell agenda-livre"><strong>Livre</strong><span class="mini">Disponível</span></div></td>';
      }
      if (slot && !slot.livre) {
        return '<td><div class="agenda-cell agenda-conflito"><strong>Ocupado</strong><span class="mini">Sem detalhes</span></div></td>';
      }
      return '<td><div class="agenda-cell agenda-conflito"><strong>Indisponível</strong><span class="mini">Sem slot disponível</span></div></td>';
    }).join('');
    return `<tr><td class="cell-slot">${h}</td>${cols}</tr>`;
  }).join('');
}

async function excluirPartida(partidaId) {
  if (!partidaId) return;
  const ok = window.confirm('Deseja excluir esta partida da agenda?');
  if (!ok) return;
  try {
    const out = await api(`/api/partidas/${partidaId}`, { method: 'DELETE' });
    alert(out.mensagem || 'Partida cancelada.');
    await carregarPartidas();
    if (document.body.dataset.page === 'agenda') {
      await carregarAgenda();
    }
  } catch (err) {
    alert(err.message || 'Falha ao excluir partida.');
  }
}

async function desfazerExclusaoPartida(partidaId) {
  if (!partidaId) return;
  try {
    const out = await api(`/api/partidas/${partidaId}/restaurar`, { method: 'POST' });
    alert(out.mensagem || 'Exclusão desfeita.');
    await carregarPartidas();
    if (document.body.dataset.page === 'agenda') {
      await carregarAgenda();
    }
  } catch (err) {
    alert(err.message || 'Falha ao desfazer exclusão.');
  }
}

async function carregarPartidas() {
  const data = document.getElementById('filtroData')?.value || '';
  const categoria = document.getElementById('filtroCategoria')?.value || '';
  const quadra = document.getElementById('filtroQuadra')?.value || '';
  const atleta = document.getElementById('filtroAtleta')?.value || '';

  const params = new URLSearchParams();
  if (data) params.set('data', data);
  if (categoria) params.set('categoria', categoria);
  if (quadra) params.set('quadra', quadra);
  if (atleta) params.set('atleta', atleta);

  const lista = await api(`/api/partidas?${params.toString()}`);
  const tbody = document.querySelector('#partidasTable tbody');
  if (!tbody) return;
  const badge = (status) => {
    if (status === 'marcada') return '<span class="status-chip status-verde">Marcada</span>';
    if (status === 'finalizada') return '<span class="status-chip status-cinza">Finalizada</span>';
    if (status === 'desconsiderada') return '<span class="status-chip status-vermelho">Desconsiderada</span>';
    if (status === 'cancelada') return '<span class="status-chip status-amarelo">Cancelada</span>';
    return `<span class="status-chip status-amarelo">${status || '-'}</span>`;
  };
  tbody.innerHTML = lista.map(p => `
    <tr>
      <td>${p.data}</td>
      <td><strong>${p.horario}</strong></td>
      <td>${p.quadra_nome}</td>
      <td><strong>${p.desafiante_nome}</strong> x <strong>${p.desafiado_nome}</strong></td>
      <td>${p.categoria_label}</td>
      <td>${badge(p.status)}</td>
      <td>
        ${(p.status === 'marcada' || p.status === 'em_andamento')
          ? `<button type="button" class="btn-excluir-partida" data-partida-id="${p.id}">Excluir</button>`
          : (p.status === 'cancelada'
            ? `<button type="button" class="btn-desfazer-exclusao" data-partida-id="${p.id}">Desfazer exclusão</button>`
            : '-')
        }
      </td>
    </tr>
  `).join('') || '<tr><td colspan="7">Nenhuma partida encontrada para os filtros selecionados.</td></tr>';

  tbody.querySelectorAll('.btn-excluir-partida').forEach((btn) => {
    btn.addEventListener('click', () => excluirPartida(btn.dataset.partidaId));
  });
  tbody.querySelectorAll('.btn-desfazer-exclusao').forEach((btn) => {
    btn.addEventListener('click', () => desfazerExclusaoPartida(btn.dataset.partidaId));
  });
}

async function apagarResultado(partidaId, onDone) {
  if (!partidaId) return;
  const ok = window.confirm('Deseja apagar este resultado e reverter o ranking da categoria?');
  if (!ok) return;
  try {
    const out = await api(`/api/apagar-resultado/${partidaId}`, { method: 'DELETE' });
    alert(out.mensagem || 'Resultado apagado com sucesso.');
    if (typeof onDone === 'function') await onDone();
  } catch (err) {
    alert(err.message || 'Falha ao apagar resultado.');
  }
}

async function carregarAtleta() {
  const atletaId = document.body.dataset.atletaId;
  if (!atletaId) return;

  const data = await api(`/api/atleta/${atletaId}`);
  const a = data.atleta;

  const resumo = document.getElementById('atletaResumo');
  if (resumo) {
    const statusChip = `<span class="status-chip ${statusClass(data.status_visual?.cor)}">${data.status_visual?.label}</span>`;
    resumo.innerHTML = `
      <h2>${a.nome}</h2>
      <div class="atleta-resumo-grid">
        <div class="stat-item"><strong>Posição</strong><br>#${a.posicao}</div>
        <div class="stat-item"><strong>Classe</strong><br>${a.classe || '-'}</div>
        <div class="stat-item"><strong>Categoria</strong><br>${a.categoria || '-'}</div>
        <div class="stat-item"><strong>Status</strong><br>${statusChip}</div>
        <div class="stat-item"><strong>Último jogo</strong><br>${a.ultimo_jogo || '-'}</div>
        <div class="stat-item"><strong>Último desafio</strong><br>${a.ultimo_desafio || '-'}</div>
        <div class="stat-item"><strong>WO consecutivos</strong><br>${a.wo_consecutivos}</div>
        <div class="stat-item"><strong>Financeiro</strong><br>${a.status_financeiro || '-'}</div>
        <div class="stat-item"><strong>Vitórias</strong><br>${data.estatisticas?.vitorias ?? 0}</div>
        <div class="stat-item"><strong>Derrotas</strong><br>${data.estatisticas?.derrotas ?? 0}</div>
        <div class="stat-item"><strong>Jogos finalizados</strong><br>${data.estatisticas?.jogos_finalizados ?? 0}</div>
        <div class="stat-item"><strong>Liberado para jogar</strong><br>${data.liberado_para_jogar ? 'Sim' : `Não (${data.motivo_status})`}</div>
      </div>
      ${data.bloqueio_secretaria ? `<p><strong>Bloqueio da secretaria:</strong> ${data.bloqueio_motivo || 'sem motivo informado'}</p>` : ''}
    `;
  }

  const desafiosUl = document.getElementById('desafiosPossiveis');
  if (desafiosUl) {
    desafiosUl.innerHTML = data.desafios_possiveis.map((d) => {
      const st = statusDesafioVisual(d);
      return `<li><strong>${d.posicao} - ${escapeHtml(d.nome)}</strong> (${escapeHtml(d.classe)}) <span class="${st.cls}">${st.label}</span><br><span class="hint">${escapeHtml(d.motivo)}</span></li>`;
    }).join('') || '<li>Sem desafios possíveis no momento.</li>';
  }

  const podeUl = document.getElementById('podeSerDesafiado');
  if (podeUl) {
    podeUl.innerHTML = data.pode_ser_desafiado_por.map(d => `<li>${d.posicao} - ${d.nome}</li>`).join('') || '<li>Nenhum atleta apto a desafiar.</li>';
  }

  const histTbody = document.querySelector('#historicoTable tbody');
  if (histTbody) {
    histTbody.innerHTML = data.historico_partidas.map(p => `
      <tr>
        <td>${p.data || '-'}</td>
        <td>${p.horario || '-'}</td>
        <td>${p.status || '-'}</td>
        <td>${p.resultado || '-'}</td>
        <td>
          ${(p.status === 'finalizada' || p.status === 'realizada')
            ? `<button type="button" class="btn-apagar-resultado" data-partida-id="${p.id}">Apagar resultado</button>`
            : '-'}
        </td>
      </tr>
    `).join('') || '<tr><td colspan="5">Sem histórico.</td></tr>';

    histTbody.querySelectorAll('.btn-apagar-resultado').forEach((btn) => {
      btn.addEventListener('click', () => apagarResultado(btn.dataset.partidaId, carregarAtleta));
    });
  }
}

async function carregarAtletasSelects() {
  const atletas = await api('/api/atletas');

  const options = atletas
    .filter(a => !a.retirado)
    .sort((a,b) => a.nome.localeCompare(b.nome))
    .map(a => `<option value="${a.id}">${a.nome} (${a.categoria} - #${a.posicao})</option>`)
    .join('');

  ['agendarDesafiante','agendarDesafiado','statusAtletaId','desafioAtleta'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = options;
  });

  const partidas = await api('/api/partidas');
  const partidaSel = document.getElementById('resultadoPartida');
  if (partidaSel) {
    partidaSel.innerHTML = partidas
      .filter(p => p.status === 'marcada')
      .map(p => `<option value="${p.id}">${p.id} - ${p.data} ${p.horario} - ${p.desafiante_nome} x ${p.desafiado_nome}</option>`)
      .join('');
  }

  atualizarOpcoesVencedorSecretaria(partidas);
}

function atualizarOpcoesVencedorSecretaria(partidasBase = null) {
  const partidaSel = document.getElementById('resultadoPartida');
  const vencedorSel = document.getElementById('resultadoVencedor');
  if (!partidaSel || !vencedorSel) return;

  const atualizar = async () => {
    const partidas = partidasBase || await api('/api/partidas');
    const partida = partidas.find((item) => item.id === partidaSel.value);
    if (!partida) {
      vencedorSel.innerHTML = '<option value="">Selecione a partida</option>';
      return;
    }
    vencedorSel.innerHTML = `
      <option value="${partida.desafiante}">${partida.desafiante_nome} (desafiante)</option>
      <option value="${partida.desafiado}">${partida.desafiado_nome} (desafiado)</option>
    `;
  };

  atualizar();
  partidaSel.onchange = atualizar;
}

async function configurarSecretaria() {
  async function carregarPendentesSecretaria() {
    const tbody = document.querySelector('#pendentesSecretariaTable tbody');
    if (!tbody) return;
    const lista = await api('/api/secretaria/desafios-pendentes');
    tbody.innerHTML = lista.map((p) => `
      <tr>
        <td><strong>${p.desafiante_nome}</strong> x <strong>${p.desafiado_nome}</strong></td>
        <td>${p.categoria_label || p.categoria || '-'}</td>
        <td>${(p.data_desafio || '').replace('T', ' ') || '-'}</td>
        <td><button type="button" class="btn-agendar-pendente" data-partida-id="${p.id}" data-desafiante="${p.desafiante}" data-desafiado="${p.desafiado}">Agendar este jogo</button></td>
      </tr>
    `).join('') || '<tr><td colspan="4">Sem desafios pendentes.</td></tr>';

    tbody.querySelectorAll('.btn-agendar-pendente').forEach((btn) => {
      btn.addEventListener('click', () => {
        const partidaId = btn.dataset.partidaId;
        const desafiante = btn.dataset.desafiante;
        const desafiado = btn.dataset.desafiado;
        const hidden = document.getElementById('agendarPartidaPendenteId');
        const sDesafiante = document.getElementById('agendarDesafiante');
        const sDesafiado = document.getElementById('agendarDesafiado');
        if (hidden) hidden.value = partidaId;
        if (sDesafiante) sDesafiante.value = desafiante;
        if (sDesafiado) sDesafiado.value = desafiado;
        setMsg('msgPendentesSecretaria', 'Desafio carregado no formulário. Defina data, horário e quadra para confirmar.', true);
        document.getElementById('formAgendar')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    });
  }

  const formAgendar = document.getElementById('formAgendar');
  if (formAgendar) {
    formAgendar.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const partidaPendenteId = document.getElementById('agendarPartidaPendenteId')?.value || '';
        const payload = {
          desafiante: document.getElementById('agendarDesafiante').value,
          desafiado: document.getElementById('agendarDesafiado').value,
          data: document.getElementById('agendarData').value,
          horario: document.getElementById('agendarHorario').value,
          quadra: document.getElementById('agendarQuadra').value,
          tipo_confronto: document.getElementById('agendarTipo').value,
          status: 'marcada',
        };
        const endpoint = partidaPendenteId ? '/api/secretaria/agendar-pendente' : '/api/agendar';
        const body = partidaPendenteId ? { ...payload, partida_id: partidaPendenteId } : payload;
        const out = await api(endpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body),
        });
        setMsg('msgAgendar', out.mensagem, true);
        const hidden = document.getElementById('agendarPartidaPendenteId');
        if (hidden) hidden.value = '';
        await carregarPendentesSecretaria();
      } catch (err) {
        setMsg('msgAgendar', err.message, false);
      }
    });
  }

  const formResultado = document.getElementById('formResultado');
  if (formResultado) {
    formResultado.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const payload = {
          partida_id: document.getElementById('resultadoPartida').value,
          vencedor: document.getElementById('resultadoVencedor').value,
          placar: document.getElementById('resultadoPlacar').value,
          wo: document.getElementById('resultadoWO').value === 'true',
          observacoes: document.getElementById('resultadoObs').value,
        };
        const out = await api('/api/registrar-resultado', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
        setMsg('msgResultado', out.mensagem, true);
        await carregarAtletasSelects();
        await carregarPendentesSecretaria();
      } catch (err) {
        setMsg('msgResultado', err.message, false);
      }
    });
  }

  const formStatus = document.getElementById('formStatusAtleta');
  if (formStatus) {
    formStatus.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const payload = {
          atleta_id: document.getElementById('statusAtletaId').value,
          ativo: document.getElementById('statusAtivo').value === 'true',
          neutro: document.getElementById('statusNeutro').value === 'true',
          retirado: document.getElementById('statusRetirado').value === 'true',
          status_financeiro: document.getElementById('statusFinanceiro').value,
          bloqueio_secretaria: document.getElementById('statusBloqueioSecretaria')?.value === 'true',
          bloqueio_motivo: document.getElementById('statusMotivoBloqueio')?.value || '',
          observacoes: document.getElementById('statusObs').value,
        };
        const out = await api('/api/secretaria/status-atleta', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
        setMsg('msgStatusAtleta', out.mensagem, true);
        await carregarAtletasSelects();
      } catch (err) {
        setMsg('msgStatusAtleta', err.message, false);
      }
    });
  }

  await carregarPendentesSecretaria();
}

async function carregarDesafios() {
  const atletaId = document.getElementById('desafioAtleta')?.value;
  if (!atletaId) return;
  const desafios = await api(`/api/desafios/${atletaId}`);
  const tbody = document.querySelector('#desafiosTable tbody');
  if (!tbody) return;

  nomeAtletaSelecionadoDesafio = document.querySelector(`#desafioAtleta option[value="${atletaId}"]`)?.textContent?.split(' (')[0] || 'DESAFIANTE';

  tbody.innerHTML = desafios.map(d => {
    const st = statusDesafioVisual(d);
    return `
    <tr>
      <td>${d.posicao}</td>
      <td>${d.nome}</td>
      <td>${d.classe}</td>
      <td><span class="${st.cls}">${st.label}</span></td>
      <td>${d.motivo}</td>
      <td><button type="button" class="btn-gerar-quadro-desafio" data-oponente="${d.nome}" data-oponente-id="${d.id || ''}" ${d.pode_desafiar ? '' : 'disabled'}>Gerar quadro</button></td>
    </tr>
  `;
  }).join('') || '<tr><td colspan="6">Sem desafios possíveis.</td></tr>';

  const first = desafios.find(x => x.pode_desafiar);
  document.getElementById('qDesafio').textContent = first ? `${nomeAtletaSelecionadoDesafio} x ${first.nome}` : `${nomeAtletaSelecionadoDesafio} x NOME DO DESAFIADO`;

  const hoje = new Date();
  const limite = new Date();
  limite.setDate(hoje.getDate() + 10);
  document.getElementById('qLimite').textContent = `DE = ${hoje.toLocaleDateString('pt-BR')} ATÉ = ${limite.toLocaleDateString('pt-BR')}`;

  // Se já houver jogo marcado para o atleta, usa dia/horário reais no quadro.
  const partidasAtleta = await api(`/api/partidas?atleta=${encodeURIComponent(nomeAtletaSelecionadoDesafio)}`);
  const marcada = partidasAtleta.find(p => p.status === 'marcada');
  document.getElementById('qDia').textContent = marcada ? marcada.data : '___';
  document.getElementById('qHora').textContent = marcada ? marcada.horario : '___';

  if (marcada) {
    document.getElementById('qDesafio').textContent = `${marcada.desafiante_nome} x ${marcada.desafiado_nome}`;
  }

  document.querySelectorAll('.btn-gerar-quadro-desafio').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const oponente = btn.dataset.oponente;
      const oponenteId = btn.dataset.oponenteId;
      document.getElementById('qDesafio').textContent = `${nomeAtletaSelecionadoDesafio} x ${oponente}`;

      const partidas = await api(`/api/partidas?atleta=${encodeURIComponent(nomeAtletaSelecionadoDesafio)}`);
      const marcadaPar = partidas.find((p) =>
        p.status === 'marcada' &&
        ((p.desafiante_nome === nomeAtletaSelecionadoDesafio && p.desafiado_nome === oponente) ||
         (p.desafiado_nome === nomeAtletaSelecionadoDesafio && p.desafiante_nome === oponente))
      );
      document.getElementById('qDia').textContent = marcadaPar ? marcadaPar.data : '___';
      document.getElementById('qHora').textContent = marcadaPar ? marcadaPar.horario : '___';

      const desafianteId = document.getElementById('desafioAtleta')?.value;
      if (desafianteId && oponenteId) {
        await enviarDesafioParaSecretaria(desafianteId, oponenteId);
      }
    });
  });
}

async function carregarPartidasAtletaParaResultado() {
  const atletaId = document.getElementById('atletaResultadoAtleta')?.value;
  if (!atletaId) return;

  const data = await api(`/api/partidas-atleta/${atletaId}`);
  partidasLancaveisAtleta = data.lancaveis || [];

  const partidaSelect = document.getElementById('partidaResultadoAtleta');
  if (partidaSelect) {
    partidaSelect.innerHTML = partidasLancaveisAtleta.length
      ? partidasLancaveisAtleta.map((p) =>
        `<option value="${p.id}">${p.id} - ${p.data} ${p.horario} - ${p.desafiante_nome} x ${p.desafiado_nome}</option>`
      ).join('')
      : '<option value="">Sem partidas pendentes</option>';
  }

  const tbody = document.querySelector('#pendentesAtletaTable tbody');
  if (tbody) {
    tbody.innerHTML = partidasLancaveisAtleta.length
      ? partidasLancaveisAtleta.map((p) => `
        <tr>
          <td>${p.data}</td>
          <td>${p.horario}</td>
          <td>${p.quadra_nome}</td>
          <td>${p.desafiante_nome} x ${p.desafiado_nome}</td>
          <td>${p.status}</td>
        </tr>
      `).join('')
      : '<tr><td colspan="5">Nenhuma partida pendente para este atleta.</td></tr>';
  }

  const resultadosTbody = document.querySelector('#resultadosAtletaTable tbody');
  if (resultadosTbody) {
    const historico = data.historico || [];
    resultadosTbody.innerHTML = historico.length
      ? historico.map((p) => `
        <tr>
          <td>${p.data || '-'}</td>
          <td>${p.horario || '-'}</td>
          <td>${p.desafiante_nome} x ${p.desafiado_nome}</td>
          <td>${p.resultado || '-'}</td>
          <td>${p.status || '-'}</td>
          <td>
            ${(p.status === 'finalizada' || p.status === 'realizada')
              ? `<button type="button" class="btn-apagar-resultado" data-partida-id="${p.id}">Apagar resultado</button>`
              : '-'}
          </td>
        </tr>
      `).join('')
      : '<tr><td colspan="6">Sem resultados lançados para este atleta.</td></tr>';

    resultadosTbody.querySelectorAll('.btn-apagar-resultado').forEach((btn) => {
      btn.addEventListener('click', () => apagarResultado(btn.dataset.partidaId, carregarPartidasAtletaParaResultado));
    });
  }

  atualizarOpcoesVencedorAtleta();
}

function atualizarOpcoesVencedorAtleta() {
  const partidaId = document.getElementById('partidaResultadoAtleta')?.value;
  const vencedorSelect = document.getElementById('vencedorResultadoAtleta');
  if (!vencedorSelect) return;

  const partida = partidasLancaveisAtleta.find((p) => p.id === partidaId);
  if (!partida) {
    vencedorSelect.innerHTML = '<option value="">Selecione uma partida</option>';
    return;
  }

  vencedorSelect.innerHTML = `
    <option value="${partida.desafiante}">${partida.desafiante_nome}</option>
    <option value="${partida.desafiado}">${partida.desafiado_nome}</option>
  `;
}

async function configurarResultadoAtleta() {
  await carregarAtletasSelects();
  const select = document.getElementById('atletaResultadoAtleta');
  const partidaSelect = document.getElementById('partidaResultadoAtleta');
  const form = document.getElementById('formResultadoAtleta');
  if (!select || !partidaSelect || !form) return;

  const atletas = await api('/api/atletas');
  const options = atletas
    .filter((a) => !a.retirado)
    .sort((a, b) => a.nome.localeCompare(b.nome))
    .map((a) => `<option value="${a.id}">${a.nome} (${a.categoria} - #${a.posicao})</option>`)
    .join('');
  select.innerHTML = options;

  select.addEventListener('change', carregarPartidasAtletaParaResultado);
  partidaSelect.addEventListener('change', atualizarOpcoesVencedorAtleta);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const payload = {
        partida_id: document.getElementById('partidaResultadoAtleta').value,
        vencedor: document.getElementById('vencedorResultadoAtleta').value,
        placar: document.getElementById('placarResultadoAtleta').value,
        wo: document.getElementById('woResultadoAtleta').value === 'true',
        observacoes: document.getElementById('obsResultadoAtleta').value,
      };
      const out = await api('/api/registrar-resultado', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      setMsg('msgResultadoAtleta', out.mensagem, true);
      await carregarPartidasAtletaParaResultado();
      await carregarRanking();
    } catch (err) {
      setMsg('msgResultadoAtleta', err.message, false);
    }
  });

  await carregarPartidasAtletaParaResultado();
}

function boot() {
  const page = document.body.dataset.page;
  aplicarFallbackLogos();
  destacarMenuAtivo();

  if (page === 'ranking') {
    carregarRanking();
    document.getElementById('filtroRanking')?.addEventListener('change', carregarRanking);
    document.getElementById('btnCopiarRanking')?.addEventListener('click', copiarRanking);
    document.getElementById('btnWhatsappRanking')?.addEventListener('click', compartilharRankingWhatsapp);
  }

  if (page === 'agenda') {
    const agendaData = document.getElementById('agendaData');
    if (agendaData) {
      agendaData.value = new Date().toISOString().slice(0, 10);
    }
    carregarAgenda();
    document.getElementById('btnAtualizarAgenda')?.addEventListener('click', carregarAgenda);
  }

  if (page === 'partidas') {
    carregarPartidas();
    document.getElementById('btnFiltrarPartidas')?.addEventListener('click', carregarPartidas);
  }

  if (page === 'atleta') {
    carregarAtleta();
  }

  if (page === 'secretaria') {
    carregarAtletasSelects().then(configurarSecretaria);
  }

  if (page === 'desafio') {
    carregarAtletasSelects().then(() => {
      document.getElementById('btnCarregarDesafios')?.addEventListener('click', carregarDesafios);
      document.getElementById('btnCopiarQuadro')?.addEventListener('click', copiarQuadroDesafio);
      carregarDesafios();
    });
  }

  if (page === 'resultado-atleta') {
    configurarResultadoAtleta();
  }
}

boot();
