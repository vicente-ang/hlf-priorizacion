/* Front «pulso.» del HLF. Lee window.HLF (web/datos.js, generado por `python -m web.construir`) y no calcula
   prioridades: muestra la lista vigente del motor y la propuesta del agente IA. Lo único que hace es aplicar las
   decisiones de las personas (aceptar, rechazar, prioridad absoluta, revertir) con las mismas reglas que
   ia/decisiones.py, guardarlas en este navegador y, si corre con `python -m web.servidor`, en el registro CSV. */
'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = (n, d = 1) => n == null || Number.isNaN(Number(n)) ? '—' : Number(n).toLocaleString('es-CL', {maximumFractionDigits: d});
const fecha = iso => { if (!iso) return '—'; const [a, m, d] = String(iso).slice(0, 10).split('-'); return `${d}-${m}-${a}`; };
const corta = iso => { if (!iso) return '—'; const [, m, d] = String(iso).slice(0, 10).split('-'); return `${d}-${m}`; };
const pct = (a, b) => b ? fmt(a / b * 100) + '%' : '—';

const ICONS = {
  overview: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
  inbox: '<path d="M4 4h16l2 12v4H2v-4L4 4Z"/><path d="M2 14h6l2 3h4l2-3h6"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18M7 14h3M14 14h3M7 17h3"/>',
  'arrow-right': '<path d="M4 12h16M14 6l6 6-6 6"/>', 'arrow-left': '<path d="M20 12H4M10 6l-6 6 6 6"/>',
  'chevron-left': '<path d="m14 6-6 6 6 6"/>', 'chevron-right': '<path d="m9 6 6 6-6 6"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  users: '<circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M17 4a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 4v3"/>',
  chart: '<path d="M4 3v18h17M8 16v-5M13 16V7M18 16V4"/>', clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  activity: '<path d="M2 12h5l3-8 4 16 3-8h5"/>', info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  document: '<path d="M6 3h8l4 4v14H6V3Z"/><path d="M14 3v5h4M9 12h6M9 16h6"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M4 17v4h16v-4"/>', close: '<path d="m6 6 12 12M18 6 6 18"/>',
  alert: '<path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5M12 17h.01"/>', check: '<path d="m5 12 4 4L19 6"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>', star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9L12 3Z"/>',
  dollar: '<path d="M12 2v20M17 6.5C17 4.6 14.8 3.5 12 3.5S7 4.7 7 6.8c0 4.7 10 2.6 10 7.4 0 2.1-2.2 3.3-5 3.3s-5-1.1-5-3"/>'
};
const icon = n => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ICONS[n] || ICONS.document}</svg>`;
const fillIcons = (root = document) => root.querySelectorAll('[data-icon]').forEach(e => { e.innerHTML = icon(e.dataset.icon); });

// ------------------------------------------------------------------------------------------- datos y estado
const D = window.HLF || {meta: {}, pacientes: [], ingresos: [], cambios: [], especialidades: [], ia: {}};
const P = D.pacientes;
const POR_ID = new Map(P.map(p => [p.id, p]));
const P90 = D.meta.p90;
const ORDEN = {alta: 0, media: 1, baja: 2};
const ETIQ = {alta: 'Alta', media: 'Media', baja: 'Baja'};
const CLASE = {alta: 'high', media: 'medium', baja: 'low'};
const state = {page: 'overview', filter: 'all', order: 'regla', listPage: 1, returnPage: 'list', patientId: null, chartMode: 'prioridad', aviso: null};

const ALMACEN = 'pulso-hlf-v1';
function leerAlmacen() {
  try { return JSON.parse(localStorage.getItem(ALMACEN)) || {}; } catch (e) { return {}; }
}
const memoria = Object.assign({perfil: 'gestora', decisiones: {}, absolutos: [], historial: []}, leerAlmacen());
function guardarAlmacen() { try { localStorage.setItem(ALMACEN, JSON.stringify(memoria)); } catch (e) { /* sin almacenamiento */ } }
const PERFILES = {gestora: {nombre: 'Gestora de demanda', corto: 'GD', otro: 'jefe de especialidad'}, jefe: {nombre: 'Jefe de especialidad', corto: 'JE', otro: 'gestora de demanda'}};

const iniciales = nombre => { const w = String(nombre).replace(/^Paciente\s+/, '').split(/\s+/); return /^\d/.test(w[0] || '') ? 'IC' : (w[0] || '?').slice(0, 2).toUpperCase(); };
const badgePrioridad = (c, extra = '') => c ? `<span class="badge ${CLASE[c]}"><span>●</span> ${ETIQ[c]}${extra}</span>` : '<span class="badge neutral">Por revisar</span>';

// -------------------------------------------------------- decisiones (mismas reglas que ia/decisiones.py)
const masAlta = (...cs) => cs.filter(c => c in ORDEN).sort((a, b) => ORDEN[a] - ORDEN[b])[0];
function categoriaVista(p, decisiones = memoria.decisiones) {
  const d = decisiones[p.id]?.decision, piso = p.carril ? 'alta' : null;
  if (d === 'ia_aceptada' && p.ia?.categoria) return masAlta(p.ia.categoria, piso);
  if (d === 'ia_rechazada') return masAlta(p.t1, piso);
  return p.ia?.categoria_final || masAlta(p.t1, piso) || p.prioridad;
}
function estado(p) {
  if (memoria.absolutos.includes(p.id)) return 'prioridad absoluta';
  return {ia_aceptada: 'aceptada', ia_rechazada: 'rechazada'}[memoria.decisiones[p.id]?.decision] || 'pendiente';
}
function posiciones(decisiones = memoria.decisiones, absolutos = memoria.absolutos) {
  // Puesto por especialidad en los dos órdenes: lista vigente (regla) y propuesta IA, con prioridad absoluta primero
  const regla = new Map(), ia = new Map(), porEsp = {};
  const cat = p => ORDEN[categoriaVista(p, decisiones)];
  P.forEach(p => (porEsp[p.especialidad] ||= []).push(p));
  for (const lista of Object.values(porEsp)) {
    const abs = x => { const i = absolutos.indexOf(x.id); return i < 0 ? 1e6 : i; };
    [...lista].sort((a, b) => abs(a) - abs(b) || a.puesto - b.puesto).forEach((p, i) => regla.set(p.id, i + 1));
    [...lista].sort((a, b) => abs(a) - abs(b) || cat(a) - cat(b)
      || (b.ia?.puntaje ?? -1) - (a.ia?.puntaje ?? -1) || String(a.fecha_ingreso).localeCompare(String(b.fecha_ingreso)))
      .forEach((p, i) => ia.set(p.id, i + 1));
  }
  return {regla, ia};
}
let POS = posiciones();

async function registrarEnServidor(fila) {
  if (!location.protocol.startsWith('http')) return;
  try { await fetch('/api/decision', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(fila)}); }
  catch (e) { /* sin servidor: queda en este navegador */ }
}
function decidir(p, accion, motivo) {
  const perfil = PERFILES[memoria.perfil];
  const antes = POS.ia.get(p.id), antesRegla = POS.regla.get(p.id);
  const decs = {...memoria.decisiones};
  let abs = [...memoria.absolutos];
  let previa = '';
  if (accion === 'ia_aceptada' || accion === 'ia_rechazada') decs[p.id] = {decision: accion};
  if (accion === 'prioridad_absoluta') abs.push(p.id);
  if (accion === 'revertida') {
    previa = decs[p.id]?.decision || (abs.includes(p.id) ? 'prioridad_absoluta' : '');
    delete decs[p.id];
    abs = abs.filter(x => x !== p.id);
  }
  const nuevo = posiciones(decs, abs);
  memoria.decisiones = decs;
  memoria.absolutos = abs;
  POS = nuevo;
  const despues = POS.ia.get(p.id);
  const ahora = new Date(), local = new Date(ahora - ahora.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
  const fila = {fecha_registro: local, usuario: perfil.nombre, rol: perfil.nombre.toLowerCase(),
    fecha_lista: D.meta.corte, especialidad: p.especialidad, id_paciente: p.id, puesto_propuesto: p.ia?.puesto_final ?? p.puesto,
    motivo_propuesto: p.ia ? `IA: ${p.ia.categoria} (${p.ia.puntaje})` : 'lista vigente', decision: accion, puesto_final: despues,
    motivo: accion === 'revertida' ? `revierte: ${previa.replace('ia_', '').replace('_', ' ')}${motivo ? ' · ' + motivo : ''}` : motivo,
    modo: 'ia', version_regla: D.ia?.rubrica || ''};
  memoria.historial.unshift({...fila, nombre: p.nombre, antes, despues, antes_regla: antesRegla, despues_regla: POS.regla.get(p.id)});
  guardarAlmacen();
  registrarEnServidor(fila);
  const verbo = {ia_aceptada: 'Propuesta aceptada', ia_rechazada: 'Propuesta rechazada', prioridad_absoluta: 'Prioridad absoluta', revertida: 'Decisión revertida'}[accion];
  state.aviso = {tipo: 'ok', texto: `${verbo} para ${p.nombre}: propuesta IA #${antes} → #${despues}` +
    (accion === 'prioridad_absoluta' || previa === 'prioridad_absoluta' ? ` · lista vigente #${antesRegla} → #${POS.regla.get(p.id)}` : '') + '.'};
}

// ------------------------------------------------------------------------------------------- navegación
function showPage(page, focus = true) {
  state.page = page;
  $$('.page').forEach(e => { e.hidden = e.id !== page + '-page'; });
  const nav = page === 'patient' ? state.returnPage : page;
  $$('.nav-button').forEach(b => { b.classList.toggle('selected', b.dataset.page === nav); if (b.dataset.page === nav) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current'); });
  $('#breadcrumb-page').textContent = {overview: 'Resumen', list: 'Lista de espera', alertas: 'Alertas', intake: 'Nuevos ingresos', patient: 'Ficha de paciente', ia: 'Agente IA'}[page];
  if (page === 'list') renderList();
  if (page === 'alertas') renderAlertas();
  if (page === 'ia') renderIA();
  if (page === 'overview') renderOverview();
  window.scrollTo({top: 0, behavior: 'instant'});
  if (focus) $('#main-content').focus({preventScroll: true});
}
function bindPatients(root) { root.querySelectorAll('[data-open-patient]').forEach(b => { b.onclick = e => { e.stopPropagation(); openPatient(b.dataset.openPatient); }; }); }

// ------------------------------------------------------------------------------------------- resumen
function metric(label, number, unit, caption, iconName, accent = false, bottom = '') {
  return `<article class="metric ${accent ? 'accent' : ''}"><div class="metric-label">${label}${icon(iconName)}</div><div class="metric-number">${number}${unit ? `<small>${unit}</small>` : ''}</div>${caption ? `<p class="metric-caption">${caption}</p>` : ''}${bottom ? `<span class="metric-bottom-tag">${bottom}</span>` : ''}</article>`;
}
function renderOverview() {
  const sobre = P.filter(p => p.sobre_p90), alta = P.filter(p => p.prioridad === 'alta'), carril = P.filter(p => p.carril);
  $('#metrics').innerHTML = metric('Personas en la lista vigente', fmt(P.length), '', `Corte del lunes ${fecha(D.meta.corte)}`, 'users', true, `${D.especialidades.length} especialidades`)
    + metric('Umbral del 90%', fmt(P90), 'días', 'El 90% de la lista espera este tiempo o menos', 'chart')
    + metric('Quienes más han esperado', fmt(sobre.length), 'personas', `Superan los ${fmt(P90)} días · ${pct(sobre.length, P.length)} de la lista`, 'clock')
    + metric('Prioridad alta hoy', fmt(alta.length), 'personas', `${carril.length} en carril rápido por un evento grave reciente`, 'activity');
  renderHistogram();
  $('#histogram-tag').textContent = `${fmt(P.length)} personas`;
  $('#specialty-subtitle').textContent = `${D.especialidades.length} especialidades en la lista vigente`;
  $('#specialty-breakdown').innerHTML = D.especialidades.map(e => `<div class="specialty-row"><div class="specialty-row-top"><span>${esc(e.nombre)}</span><strong>${e.n}</strong></div><div class="specialty-bar"><i style="width:${e.n / D.especialidades[0].n * 100}%"></i></div><small>${pct(e.n, P.length)} de la lista · ${e.sobre_umbral} sobre el umbral · ${e.alta} con prioridad alta</small></div>`).join('');
  $('#changes-tag').textContent = `${D.n_cambios} con antecedentes nuevos`;
  $('#recent-changes').innerHTML = D.cambios.slice(0, 5).map(c => {
    const flecha = c.antes && c.antes !== c.ahora ? ` · puesto ${c.antes} → ${c.ahora}` : ` · puesto ${c.ahora}`;
    return `<button class="change-row" data-open-patient="${c.id}" aria-label="Ver ficha de ${esc(c.nombre)}"><span class="change-avatar">${iniciales(c.nombre)}</span><span class="change-copy"><b>${esc(c.nombre)}</b><small>${esc(c.especialidad)}${flecha} · ${esc(c.nuevos.join('; '))}</small></span><span class="change-state">${badgePrioridad(c.prioridad)}</span>${icon('chevron-right')}</button>`;
  }).join('') || '<p class="empty-note">Sin antecedentes nuevos desde el corte anterior.</p>';
  $('#intake-preview-title').textContent = `${D.ingresos.length} ingresos por revisar`;
  const ia = D.ia || {};
  $('#ia-preview').innerHTML = ia.evaluados ? `<div class="panel-heading"><div><h2>Agente IA en Amazon Bedrock</h2><p>${esc(ia.modelo_nombre || 'Bedrock')} leyó la historia de cada paciente en lista y propone su categoría y su orden, citando la evidencia</p></div><button class="button secondary" data-goto="ia">Ver el agente ${icon('arrow-right')}</button></div><div class="ia-strip"><div><small>Evaluados</small><strong>${fmt(ia.evaluados)}</strong><p>${ia.errores} errores</p></div><div><small>Propone subir de grupo</small><strong>${fmt(ia.suben)}</strong><p>Se aplica con el piso de la regla</p></div><div><small>Propone bajar</small><strong>${fmt(ia.bajan)}</strong><p>Lo confirma el jefe de especialidad</p></div><div><small>Pertinencia</small><strong>${ia.pertinencia ? `${ia.pertinencia.descartados_por_ia}/${ia.pertinencia.no_relacionados}` : '—'}</strong><p>Eventos no relacionados que descartó</p></div></div>` : '';
  bindPatients($('#overview-page'));
  $$('#overview-page [data-goto]').forEach(b => { b.onclick = () => showPage(b.dataset.goto); });
}
// ------------------------------------------------------------------------------------------- alertas entre cortes
function renderAlertas() {
  const a = D.alertas || {items: [], resumen: {}, n: 0};
  const items = a.items || [];
  $('#alertas-pill').textContent = `${items.length} ${items.length === 1 ? 'alerta' : 'alertas'}`;
  $('#alertas-proximo').textContent = `lunes ${fecha(D.meta.proximo_corte)} · 07:00`;
  $('#alertas-subtitle').textContent = a.desde && a.hasta
    ? `Desde el corte del ${fecha(a.desde)} hasta el ${fecha(a.hasta)}` : 'Sin período';
  const r = a.resumen || {};
  const carril = r['Entró al carril rápido'] || 0, subio = r['Subió'] || 0;
  const salio = r['Salió de la lista'] || 0, sinDatos = r['Sin datos recientes'] || 0;
  $('#alertas-metrics').innerHTML =
    metric('Alertas esta semana', fmt(items.length), '', 'Eventos y cambios desde el último corte', 'alert', items.length > 0)
    + metric('Entraron al carril rápido', fmt(carril), '', 'Evento grave reciente: revisar hoy', 'activity')
    + metric('Subieron de puesto', fmt(subio), '', 'Si se repriorizara hoy (proyección)', 'arrow-right')
    + metric('Sin datos recientes', fmt(sinDatos), '', '180 días sin eventos ni mediciones: llamar', 'clock');
  $('#alertas-rows').innerHTML = items.length ? items.map(it => {
    const flecha = it.delta != null && it.delta !== 0
      ? `<b>#${it.puesto_proyectado}</b> <small>(${it.delta > 0 ? '↑' : '↓'}${Math.abs(it.delta)})</small>`
      : (it.puesto_proyectado != null ? `#${it.puesto_proyectado}` : '—');
    const enLista = it.puesto_vigente != null ? `#${it.puesto_vigente}` : '—';
    return `<tr>
      <td><div class="change-copy" style="display:flex;align-items:center;gap:10px"><span class="change-avatar">${iniciales(it.nombre)}</span><span><b>${esc(it.nombre)}</b><br><small>${esc(it.id)} · prioridad ${esc(ETIQ[it.prioridad_inicial] || it.prioridad_inicial || '—')}</small></span></div></td>
      <td>${esc(it.especialidad || '—')}</td>
      <td><span class="badge ${it.grave ? 'high' : 'neutral'}">${esc(it.tipo)}</span><div><small>${esc(it.detalle || '')}</small></div></td>
      <td>${enLista}</td>
      <td>${flecha}</td>
      <td>${it.en_lista ? `<button class="button secondary" data-open-patient="${esc(it.id)}">Ver ficha ${icon('chevron-right')}</button>` : ''}</td>
    </tr>`;
  }).join('') : '<tr><td colspan="6" class="empty-note">Sin alertas desde el último corte: la lista vigente no ha cambiado.</td></tr>';
  bindPatients($('#alertas-page'));
}

function renderHistogram() {
  const values = P.map(p => p.dias_espera);
  const step = 60, maxX = Math.max(step, Math.ceil(Math.max(...values) / step) * step);
  const n = maxX / step;
  const bins = Array.from({length: n}, (_, i) => ({lo: i * step, hi: (i + 1) * step, count: values.filter(v => v >= i * step && (i === n - 1 ? v <= (i + 1) * step : v < (i + 1) * step)).length}));
  const W = 690, H = 255, L = 44, R = 22, T = 40, B = 42, pw = W - L - R, ph = H - T - B;
  const pasoY = Math.max(5, Math.ceil(Math.max(...bins.map(b => b.count)) / 5 / 5) * 5);
  const peak = Math.ceil(Math.max(...bins.map(b => b.count)) / pasoY) * pasoY;
  const x = v => L + v / maxX * pw, y = v => T + ph - v / peak * ph, th = x(P90);
  const grid = Array.from({length: peak / pasoY + 1}, (_, i) => { const v = pasoY * i; return `<line x1="${L}" y1="${y(v)}" x2="${W - R}" y2="${y(v)}" stroke="#e8eee2" stroke-dasharray="3 4"/><text x="${L - 11}" y="${y(v) + 3}" text-anchor="end" fill="#7c8d72" font-size="10">${fmt(v)}</text>`; }).join('');
  const bars = bins.map(b => { const sobre = values.some(v => v >= b.lo && v <= b.hi && v > P90); return `<rect x="${x(b.lo) + 3}" y="${y(b.count)}" width="${pw / bins.length - 6}" height="${ph * b.count / peak}" rx="3" fill="${sobre ? '#d1aa66' : '#6f9579'}"><title>${b.lo}–${b.hi} días: ${b.count} personas</title></rect>`; }).join('');
  const ticks = Array.from({length: Math.floor(maxX / 120) + 1}, (_, i) => i * 120).map(v => `<text x="${x(v)}" y="${H - B + 20}" fill="#9aa98e" font-size="10" text-anchor="middle">${v}</text>`).join('');
  $('#histogram').innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Histograma de ${P.length} personas por días de espera. Umbral del 90% en ${P90} días."><rect x="${th}" y="${T}" width="${Math.max(0, W - R - th)}" height="${ph}" fill="#fcf7ed"/>${grid}${bars}<line x1="${th}" y1="25" x2="${th}" y2="${H - B}" stroke="#b9914e" stroke-width="1.4" stroke-dasharray="4 4"/><rect x="${th - 49}" y="7" width="98" height="23" rx="4" fill="#f8eed9"/><text x="${th}" y="22" text-anchor="middle" fill="#a38147" font-size="10">90% · ${fmt(P90)} días</text>${ticks}<text x="${W - R}" y="${H - 3}" text-anchor="end" fill="#9aa98e" font-size="9">Días de espera</text></svg>`;
  const sobre = values.filter(v => v > P90).length, bajo = values.length - sobre;
  $('#histogram-footer').innerHTML = `<span><b>${fmt(bajo)} personas (${pct(bajo, values.length)})</b> hasta el umbral</span><span><b>${fmt(sobre)} personas</b> con mayor antigüedad</span>`;
}

// ------------------------------------------------------------------------------------------- lista
const porRevisar = p => !!(p.verificar || (p.ia?.baja && estado(p) === 'pendiente') || p.sin_priorizar);
function prioridadVista(p) { return state.order === 'ia' ? categoriaVista(p) : p.prioridad; }
function filteredRows() {
  const q = $('#patient-search').value.trim().toLocaleLowerCase('es'), esp = $('#specialty-filter').value;
  const pos = state.order === 'ia' ? POS.ia : POS.regla;
  return P.filter(p => {
    if (esp && p.especialidad !== esp) return false;
    if (q && !`${p.nombre} ${p.id} ${p.diagnostico} ${p.especialidad}`.toLocaleLowerCase('es').includes(q)) return false;
    if (state.filter === 'carril') return p.carril;
    if (state.filter === 'p90') return p.sobre_p90;
    if (state.filter === 'revisar') return porRevisar(p);
    if (state.filter in ORDEN) return prioridadVista(p) === state.filter;
    return true;
  }).sort((a, b) => pos.get(a.id) - pos.get(b.id) || a.especialidad.localeCompare(b.especialidad, 'es'));
}
function celdaIA(p) {
  if (!p.ia || !p.ia.categoria) return '<span class="badge neutral">Sin propuesta</span>';
  const e = estado(p);
  const flecha = p.ia.sube ? '↑ ' : p.ia.baja ? '↓ ' : '';
  const tag = e === 'pendiente' ? '' : `<small class="estado-tag">${e}</small>`;
  return `<span class="badge ${CLASE[p.ia.categoria]}">${flecha}${ETIQ[p.ia.categoria]} · ${p.ia.puntaje}</span>${tag}`;
}
function renderList() {
  POS = posiciones();
  const esp = $('#specialty-filter').value;
  const base = P.filter(p => !esp || p.especialidad === esp);
  $('#tab-all').textContent = base.length;
  $('#tab-carril').textContent = base.filter(p => p.carril).length;
  $('#tab-p90').textContent = base.filter(p => p.sobre_p90).length;
  $('#tab-revisar').textContent = base.filter(porRevisar).length;
  $('#order-summary').textContent = state.order === 'ia'
    ? `Propuesta del agente (${D.ia?.modelo_nombre || 'Bedrock'}) con el piso de la regla y las decisiones de hoy`
    : `Lista vigente: corte del lunes ${fecha(D.meta.corte)} · regla ${D.meta.version_regla}`;
  $$('[data-order]').forEach(b => { const s = b.dataset.order === state.order; b.classList.toggle('active', s); b.setAttribute('aria-pressed', s); });
  const filas = filteredRows(), tam = 10, paginas = Math.max(1, Math.ceil(filas.length / tam));
  state.listPage = Math.min(state.listPage, paginas);
  const visibles = filas.slice((state.listPage - 1) * tam, state.listPage * tam);
  const pos = state.order === 'ia' ? POS.ia : POS.regla;
  $('#patient-rows').innerHTML = visibles.map(p => {
    const pv = prioridadVista(p), cambio = p.t1 !== pv ? `<small>T1 ${ETIQ[p.t1] || 'sin priorizar'} → ${ETIQ[pv]}</small>` : '<small>como al ingresar</small>';
    return `<tr data-patient-id="${p.id}"><td>${String(pos.get(p.id)).padStart(2, '0')}${esp ? '' : `<small class="pos-esp">${esc(p.especialidad.slice(0, 5))}.</small>`}</td><td><div class="patient-cell"><span class="avatar">${iniciales(p.nombre)}</span><div class="table-patient-info"><button class="patient-name" data-open-patient="${p.id}" aria-label="Ver ficha de ${esc(p.nombre)}">${esc(p.nombre)}</button><small>${p.id} · ${p.edad} años · ${p.sexo}</small></div></div></td><td class="table-specialty">${esc(p.especialidad)}<small>${esc(p.diagnostico)}</small></td><td class="table-wait">${fmt(p.dias_espera)} d</td><td>${p.carril && state.order === 'regla' ? '<span class="badge alert">● Carril rápido</span>' : badgePrioridad(pv)}${cambio}</td><td>${celdaIA(p)}</td><td>${p.sobre_p90 ? '<span class="badge p90">Mayor espera</span>' : '<span class="badge neutral">Hasta el umbral</span>'}</td><td class="table-arrow">${icon('chevron-right')}</td></tr>`;
  }).join('') || '<tr><td colspan="8" class="empty-row">No hay personas que coincidan con estos filtros.</td></tr>';
  $('#list-result-count').textContent = filas.length ? `${(state.listPage - 1) * tam + 1}–${Math.min(state.listPage * tam, filas.length)} de ${filas.length} personas` : '0 personas';
  $('#page-number').textContent = `${state.listPage} / ${paginas}`;
  $('#previous-page').disabled = state.listPage <= 1;
  $('#next-page').disabled = state.listPage >= paginas;
  $$('.list-tab').forEach(b => { b.classList.toggle('active', b.dataset.filter === state.filter); b.setAttribute('aria-pressed', b.dataset.filter === state.filter); });
  $('#patient-rows').querySelectorAll('tr[data-patient-id]').forEach(tr => { tr.onclick = e => { if (!e.target.closest('button')) openPatient(tr.dataset.patientId); }; });
  bindPatients($('#patient-rows'));
}

// ------------------------------------------------------------------------------------------- ficha
function openPatient(id) {
  const p = POR_ID.get(id);
  if (!p) return;
  if (state.page !== 'patient') state.returnPage = ['overview', 'ia'].includes(state.page) ? state.page : 'list';
  state.patientId = id;
  state.chartMode = 'prioridad';
  renderPatient();
  showPage('patient');
}
function renderPatient() {
  const p = POR_ID.get(state.patientId);
  POS = posiciones();
  const ia = p.ia, e = estado(p);
  const volver = {overview: 'al resumen', ia: 'al agente IA', list: 'a la lista'}[state.returnPage];
  const hechos = p.hechos || [];
  const evidFechas = new Set((ia?.evidencia || []).map(x => String(x.fecha || '').slice(0, 10)));
  $('#patient-detail').innerHTML = `
  <button class="back-button" id="back-to-list">${icon('arrow-left')} Volver ${volver}</button>
  <div class="patient-heading"><span class="avatar">${iniciales(p.nombre)}</span><div><p class="eyebrow">FICHA DE PACIENTE</p><h1>${esc(p.nombre)}</h1><p>${p.id} · ${p.edad} años · ${p.sexo} · ${esc(p.comuna)} · ${esc(p.prevision)} · derivado desde ${esc(p.origen)}</p></div><div class="patient-heading-right">${p.sobre_p90 ? '<span class="badge p90">Mayor espera</span>' : ''}${p.carril ? '<span class="badge alert">● Carril rápido</span>' : ''}${badgePrioridad(p.prioridad)}</div></div>
  <div class="patient-facts">
   <div><small>Posición en la lista vigente</small><strong>#${String(POS.regla.get(p.id)).padStart(2, '0')}</strong><p>de ${p.de} en ${esc(p.especialidad)} · con la regla actual sería el ${p.puesto_regla_actual ?? '—'}</p></div>
   <div><small>Tiempo de espera</small><strong>${fmt(p.dias_espera)} días</strong><p>En lista desde ${fecha(p.fecha_ingreso)}</p></div>
   <div><small>Especialidad</small><strong>${esc(p.especialidad)}</strong><p>${esc(p.sub)} · ${esc(p.diagnostico)}</p></div>
   <div><small>Propuesta del agente IA</small><strong>${ia?.categoria ? '#' + String(POS.ia.get(p.id)).padStart(2, '0') : '—'}</strong><p>${ia?.categoria ? `${ETIQ[ia.categoria]} · puntaje ${ia.puntaje} · ${e}` : 'Sin propuesta'}</p></div>
  </div>
  <div class="detail-grid">
   <section class="explanation-panel"><div class="explanation-heading"><h2>¿Por qué está en esta posición?</h2><span class="example-label">Regla ${esc(D.meta.version_regla)}</span></div>
    <div class="explanation-body"><p>${esc(hechos[0] || '')} Prioridad de hoy: <b>${ETIQ[p.prioridad].toLowerCase()}</b>${p.carril ? ', en carril rápido' : ''}.</p></div>
    <div class="reason-list">${hechos.slice(1).map((h, i) => `<div class="reason-item"><span>${String(i + 1).padStart(2, '0')}</span><div><p>${esc(h)}</p></div></div>`).join('')}</div>
    <details><summary>Señales y antecedentes que consideró la regla</summary>${[...(p.senales_deterioro || []).map(s => ['Deterioro', s]), ...(p.senales_mejora || []).map(s => ['Mejoría', s]), ...(p.clusters || []).map(s => ['Cluster', s]), ...(p.no_relacionados || []).map(s => ['No mueve', s])].map(([k, v]) => `<p class="evidence-reference"><b>${k}</b> · ${esc(v)}</p>`).join('') || '<p class="evidence-reference">Sin señales registradas.</p>'}</details>
    <p class="explanation-footnote">Explicación determinista de la regla (motor/explicar.py). Es una propuesta: el equipo de gestión la valida antes de citar.</p>
   </section>
   <section class="panel evolution-panel"><div class="panel-heading"><div><h2>Evolución en la lista</h2><p>Corte a corte, los lunes de las últimas ${D.meta.cortes.length} semanas</p></div><div class="chart-toggle" role="group" aria-label="Tipo de evolución"><button data-chart-mode="prioridad">Prioridad</button><button data-chart-mode="puesto">Puesto</button><button data-chart-mode="medicion" ${Object.keys(p.mediciones || {}).length ? '' : 'disabled'}>Medición</button></div></div>
    <div class="evolution-legend"><i class="legend-dot green"></i><span id="evolution-series-label"></span></div><div id="evolution-chart" class="evolution-chart"></div><p class="chart-footnote" id="chart-footnote"></p>
    <div class="observations"><div class="observation">Prioridad de partida<b>${ETIQ[p.t1] || 'Sin priorizar'}</b>${esc(p.prioridad_origen || '')}</div><div class="observation">Plazo vigente<b>${p.plazo_dias ? fmt(p.plazo_dias) + ' días' : '—'}</b>${p.fecha_objetivo ? 'vence ' + fecha(p.fecha_objetivo) : ''}${p.dias_atraso > 0 ? ` · ${fmt(p.dias_atraso)} días de atraso` : ''}</div><div class="observation">${p.lace != null ? 'Índice LACE' : 'Último dato registrado'}<b>${p.lace != null ? fmt(p.lace) : 'hace ' + fmt(p.dias_sin_datos) + ' días'}</b>${p.lace != null ? 'riesgo de muerte o reingreso a 30 días' : (p.verificar ? esc(p.verificar) : '')}</div></div>
   </section>
  </div>
  ${ia?.categoria ? renderIAPanel(p) : ''}
  <section class="panel history-panel"><div class="panel-heading"><div><h2>Antecedentes en su historia</h2><p>Eventos, mediciones fuera de rango, diagnósticos de APS y la derivación, con su fuente</p></div><span class="neutral-tag">${p.antecedentes.length} registros</span></div>
   <div class="history-list">${p.antecedentes.map(a => {
     const citado = evidFechas.has(String(a.fecha).slice(0, 10));
     return `<article class="history-event ${citado ? 'event-evidence' : ''}"><span class="event-mark">${icon(a.tipo === 'evento' ? 'activity' : 'document')}</span><div class="event-body"><h3>${esc(a.titulo)} ${a.severidad === 'grave' ? '<span class="badge high">grave</span>' : ''} ${a.relacionado ? '' : '<span class="badge neutral">no relacionado con la derivación</span>'}</h3><p>${esc(a.fuente)} · Fecha clínica ${fecha(a.fecha)}${a.detalle ? ' · ' + esc(a.detalle) : ''}${citado ? ' · Citado por el agente IA' : ''}</p></div><time class="event-time">${corta(a.fecha)}</time></article>`;
   }).join('')}</div>
  </section>`;
  $('#back-to-list').onclick = () => showPage(state.returnPage);
  $$('[data-chart-mode]').forEach(b => { b.onclick = () => { state.chartMode = b.dataset.chartMode; renderEvolution(p); }; });
  bindDecisionButtons(p);
  renderEvolution(p);
  fillIcons($('#patient-detail'));
}
function renderIAPanel(p) {
  const ia = p.ia, e = estado(p), decidido = e !== 'pendiente', jefe = memoria.perfil === 'jefe';
  const aviso = state.aviso ? `<div class="aviso ${state.aviso.tipo}">${esc(state.aviso.texto)}</div>` : '';
  state.aviso = null;
  const recorrido = `Lista vigente #${POS.regla.get(p.id)} → propuesta IA (híbrida) #${ia.puesto_final ?? '—'} → con las decisiones de hoy #${POS.ia.get(p.id)}`;
  const nota = ia.baja && !decidido ? `<p class="soft-warning">${icon('alert')} La IA propone bajarlo de su prioridad inicial. No se aplica sola: ${jefe ? 'como jefe de especialidad puedes confirmarlo con «Aceptar propuesta».' : 'lo confirma el jefe de especialidad (cambia el perfil abajo a la izquierda).'}</p>` : '';
  return `<section class="panel ia-panel"><div class="panel-heading"><div><h2>Propuesta del agente IA</h2><p>${esc(D.ia?.modelo_nombre || 'Bedrock')} en Amazon Bedrock · rúbrica ${esc(D.ia?.rubrica || '')} · datos al ${fecha(D.ia?.corte)}</p></div><span class="badge ${decidido ? 'complete' : 'neutral'}">${e}</span></div>
   <div class="ia-body"><div class="ia-main">
    <div class="ia-score"><span class="badge ${CLASE[ia.categoria]}">● ${ETIQ[ia.categoria]}</span><strong>${ia.puntaje}</strong><small>puntaje de riesgo · confianza ${esc(ia.confianza)}</small></div>
    <p class="ia-summary">${esc(ia.resumen)}</p>
    <h3>Evidencia citada</h3><ul class="ia-evidence">${(ia.evidencia || []).map(x => `<li><b>${fecha(x.fecha)}</b> · ${esc(x.fuente)}<br>${esc(x.cita)}</li>`).join('') || '<li>Sin evidencia citada.</li>'}</ul>
    ${(ia.ignorado || []).length ? `<h3>Descartado por no estar relacionado</h3><ul class="ia-evidence muted">${ia.ignorado.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
   </div><div class="ia-actions">
    <p class="recorrido">${esc(recorrido)}</p>${nota}${aviso}
    <label class="motivo-label">Motivo <small>(obligatorio para rechazar o dar prioridad absoluta)</small><input type="text" id="motivo-ia" placeholder="Ej.: nota del CESFAM del 10-10 no concuerda"></label>
    <div class="action-row"><button class="button primary" id="btn-aceptar" ${decidido ? 'disabled' : ''}>${icon('check')} Aceptar propuesta</button><button class="button secondary" id="btn-rechazar" ${decidido ? 'disabled' : ''}>${icon('close')} Rechazar</button><button class="button secondary" id="btn-absoluta" ${memoria.absolutos.includes(p.id) ? 'disabled' : ''}>${icon('star')} Prioridad absoluta</button><button class="button secondary" id="btn-revertir" ${decidido ? '' : 'disabled'}>${icon('undo')} Revertir</button></div>
    <p class="explanation-footnote">Perfil: ${PERFILES[memoria.perfil].nombre}. Subir lo puede proponer la IA; bajar lo confirma el jefe; la regla pone el piso (evento grave relacionado ⇒ alta). Cada decisión queda registrada y se puede revertir.</p>
   </div></div></section>`;
}
function bindDecisionButtons(p) {
  if (!p.ia?.categoria) return;
  const motivo = () => ($('#motivo-ia')?.value || '').trim();
  const error = t => { state.aviso = {tipo: 'error', texto: t}; renderPatient(); };
  $('#btn-aceptar').onclick = () => {
    if (p.ia.baja && memoria.perfil !== 'jefe') return error('Bajar de categoría lo confirma el jefe de especialidad.');
    decidir(p, 'ia_aceptada', motivo()); renderPatient();
  };
  $('#btn-rechazar').onclick = () => { if (!motivo()) return error('Escribe por qué la rechazas: sirve para mejorar la rúbrica.'); decidir(p, 'ia_rechazada', motivo()); renderPatient(); };
  $('#btn-absoluta').onclick = () => { if (!motivo()) return error('La prioridad absoluta necesita un motivo.'); decidir(p, 'prioridad_absoluta', motivo()); renderPatient(); };
  $('#btn-revertir').onclick = () => { decidir(p, 'revertida', motivo()); renderPatient(); };
}
function renderEvolution(p) {
  const modo = state.chartMode, H0 = p.historial || [];
  let pts, ymin, ymax, ticks, etiqueta, nota, invertir = false, escalon = false;
  if (modo === 'medicion') {
    const [nombre, serie] = Object.entries(p.mediciones || {})[0] || ['', []];
    pts = serie.map(s => ({x: s.fecha, v: s.valor, fuera: s.fuera}));
    const vs = pts.map(q => q.v);
    ymin = Math.min(0, ...vs); ymax = Math.max(...vs) * 1.15 || 1;
    ticks = Array.from({length: 5}, (_, i) => { const v = ymin + (ymax - ymin) * i / 4; return [v, fmt(v)]; });
    etiqueta = `${nombre} (${serie[0]?.unidad || ''})`;
    nota = 'Mediciones registradas en el control ambulatorio; los puntos rellenos están fuera de rango. Un valor aislado no decide la prioridad.';
  } else if (modo === 'puesto') {
    pts = H0.map(h => ({x: h.corte, v: h.puesto}));
    ymin = 1; ymax = Math.max(p.de || 1, ...pts.map(q => q.v || 1)); invertir = true;
    ticks = [1, Math.round(ymax / 2), ymax].map(v => [v, '#' + v]);
    etiqueta = `Puesto en ${p.especialidad} (1 = primero)`;
    nota = 'Puesto en la lista vigente de cada lunes. Entre cortes el puesto no se mueve; los eventos llegan como alerta.';
  } else {
    pts = H0.map(h => ({x: h.corte, v: h.puesto == null ? null : (h.carril ? 4 : {baja: 1, media: 2, alta: 3}[h.prioridad])}));
    ymin = 1; ymax = 4; escalon = true;
    ticks = [[1, 'Baja'], [2, 'Media'], [3, 'Alta'], [4, 'Carril rápido']];
    etiqueta = 'Prioridad de hoy en cada corte';
    nota = 'Categorías de la regla en cada corte. «Carril rápido» es un evento grave relacionado en los últimos 30 días.';
  }
  const W = 620, H = 265, L = escalon ? 100 : 62, R = 28, T = 30, B = 44, pw = W - L - R, ph = H - T - B;
  const x = i => L + (pts.length > 1 ? i / (pts.length - 1) : .5) * pw;
  const y = v => invertir ? T + (v - ymin) / ((ymax - ymin) || 1) * ph : T + ph - (v - ymin) / ((ymax - ymin) || 1) * ph;
  const grid = ticks.map(([v, t]) => `<line x1="${L}" y1="${y(v)}" x2="${W - R}" y2="${y(v)}" stroke="#e8eee0" stroke-dasharray="3 5"/><text x="${L - 12}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="#98a98a">${esc(t)}</text>`).join('');
  const segs = []; let seg = [];
  pts.forEach((q, i) => { if (q.v == null) { if (seg.length) segs.push(seg); seg = []; } else seg.push([x(i), y(q.v)]); });
  if (seg.length) segs.push(seg);
  const paths = segs.map(s => { let d = `M ${s[0][0]} ${s[0][1]}`; for (let i = 1; i < s.length; i++) d += escalon ? ` H ${s[i][0]} V ${s[i][1]}` : ` L ${s[i][0]} ${s[i][1]}`; return `<path d="${d}" fill="none" stroke="#6c926f" stroke-width="2.7" stroke-linejoin="round"/>`; }).join('');
  const cada = Math.max(1, Math.ceil(pts.length / 8));
  const dots = pts.map((q, i) => { const ult = i === pts.length - 1; const yv = q.v == null ? H - B + 8 : y(q.v); const lbl = q.v == null ? 'fuera de la lista' : modo === 'prioridad' ? ticks[q.v - 1][1] : modo === 'puesto' ? '#' + q.v : fmt(q.v); return `<circle cx="${x(i)}" cy="${yv}" r="${ult ? 5.5 : 4}" fill="${q.v == null ? 'white' : (ult || q.fuera) ? '#537950' : 'white'}" stroke="#71966c" stroke-width="2"><title>${corta(q.x)}: ${esc(lbl)}</title></circle>${i % cada === 0 || ult ? `<text x="${x(i)}" y="${H - 13}" text-anchor="middle" font-size="10" fill="#99aa8c">${corta(q.x)}</text>` : ''}`; }).join('');
  $('#evolution-series-label').textContent = etiqueta;
  $('#evolution-chart').innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(etiqueta)}"><rect x="${L}" y="${T}" width="${pw}" height="${ph}" fill="#fcfdf9"/>${grid}${paths}${dots}</svg>`;
  $('#chart-footnote').textContent = nota;
  $$('[data-chart-mode]').forEach(b => { b.classList.toggle('active', b.dataset.chartMode === modo); b.setAttribute('aria-pressed', b.dataset.chartMode === modo); });
}

// ------------------------------------------------------------------------------------------- ingresos
function renderIntake() {
  const sin = D.ingresos.filter(i => i.tipo === 'sin_priorizar').length, desp = D.ingresos.length - sin, lim = D.ingresos.filter(i => i.limitada).length;
  $('#intake-pill').textContent = `${D.ingresos.length} ingresos por revisar`;
  $('#intake-metrics').innerHTML = `<span><i class="legend-dot green"></i>${sin} sin prioridad del especialista · ${desp} después del corte</span><span><i class="legend-dot amber"></i>${lim} con información clínica limitada</span>`;
  const prop = i => i.propuesta ? `${badgePrioridad(i.propuesta)}<small>${esc((i.criterios || []).join(', ') || 'guía')}${i.fuente_propuesta === 'bedrock' ? ' · leído con Bedrock' : ''}</small>` : `<span class="badge neutral">Por revisar</span><small>${esc(i.motivo_revision || 'queda para el especialista')}</small>`;
  $('#intake-rows').innerHTML = D.ingresos.map(i => `<tr data-intake-id="${i.id}"><td><div class="patient-cell"><span class="avatar">${iniciales(i.nombre)}</span><div><button class="patient-name" data-open-intake="${i.id}">${esc(i.nombre)}</button><small>${i.id} · ${i.edad} años · ${i.tipo === 'sin_priorizar' ? 'sin priorizar' : 'después del corte'}</small></div></div></td><td>${esc(i.especialidad)}<small>${esc(i.diagnostico)}</small></td><td>${fecha(i.fecha)}<small>hace ${i.dias} días</small></td><td><span class="badge ${i.limitada ? 'p90' : 'complete'}">${i.limitada ? 'Información limitada' : 'Texto de la derivación'}</span><small>${esc(i.origen)}</small></td><td>${prop(i)}</td><td class="table-arrow">${icon('chevron-right')}</td></tr>`).join('');
  $$('[data-open-intake]').forEach(b => { b.onclick = e => { e.stopPropagation(); openIntake(b.dataset.openIntake); }; });
  $$('tr[data-intake-id]').forEach(tr => { tr.onclick = () => openIntake(tr.dataset.intakeId); });
}
function openIntake(id) {
  const i = D.ingresos.find(x => x.id === id);
  const enLista = POR_ID.get(id);
  $('#intake-dialog-content').innerHTML = `<p class="eyebrow">INGRESO · ${i.id}</p><h2 class="dialog-heading" id="intake-dialog-title">${esc(i.nombre)}</h2><p class="dialog-subtitle">${i.edad} años · ${esc(i.especialidad)} · ${esc(i.diagnostico)}</p>${i.propuesta ? badgePrioridad(i.propuesta, ' (propuesta de la guía)') : '<span class="badge neutral">Por revisar</span>'}
   <ul class="dialog-list"><li><b>Lo que escribió quien derivó</b>${esc(i.texto || 'Sin texto')}</li><li><b>Origen</b>${esc(i.origen)} · recibida el ${fecha(i.fecha)} (hace ${i.dias} días)</li><li><b>Criterios de la guía que aparecen</b>${esc((i.criterios || []).join(', ') || 'ninguno')}</li><li><b>Estado</b>${i.propuesta ? `La guía propone ${ETIQ[i.propuesta].toLowerCase()} (${i.fuente_propuesta === 'bedrock' ? 'Bedrock leyó el texto' : 'reglas'}). El especialista la confirma.` : esc(i.motivo_revision || 'Queda para el especialista.')}</li><li><b>Mientras tanto</b>${enLista ? `Espera en la lista vigente con prioridad provisoria (puesto ${enLista.puesto} de ${enLista.de}). A los 21 días usa la propuesta de la guía.` : 'Entra a la lista en el próximo corte.'}</li></ul>
   <div class="dialog-note">La información limitada no implica prioridad baja ni excluye a nadie: queda visible para que alguien la complete.</div>${enLista ? `<button class="button secondary" id="dialog-open-patient">Ver ficha ${icon('arrow-right')}</button>` : ''}`;
  if (enLista) $('#dialog-open-patient').onclick = () => { $('#intake-dialog').close(); state.page = 'intake'; openPatient(id); };
  $('#intake-dialog').showModal();
}

// ------------------------------------------------------------------------------------------- agente IA
const NOMBRES_METODO = {fifo: 'Regla actual del hospital (orden de llegada)', regla: 'Regla MVP (carril + plazo)', palabras_clave: 'Palabras clave (sin LLM)', ia: 'Agente IA en Bedrock', hibrido: 'IA + piso de la regla'};
function renderIA() {
  const ia = D.ia || {};
  if (!ia.evaluados) { $('#ia-metrics').innerHTML = '<p>Aún no hay propuestas del agente. Correr python -m ia.agente y luego python -m web.construir.</p>'; return; }
  $('#ia-description').textContent = `${ia.modelo_nombre || 'Bedrock'} evalúa a cada paciente por separado con una rúbrica versionada (${ia.rubrica}) y responde en JSON validado: categoría, puntaje, evidencia y lo que descartó.`;
  $('#ia-metrics').innerHTML = metric('Pacientes evaluados', fmt(ia.evaluados), '', `${ia.errores} errores · datos al ${fecha(ia.corte)}`, 'users', true, 'Amazon Bedrock')
    + metric('Propone subir de grupo', fmt(ia.suben), 'personas', 'Se aplica con el piso de la regla', 'activity')
    + metric('Propone bajar', fmt(ia.bajan), 'personas', `Lo confirma el jefe · ${ia.bajan_confianza_alta} con confianza alta`, 'alert')
    + metric('Costo de la corrida', ia.costo_usd != null ? 'US$ ' + fmt(ia.costo_usd, 2) : '—', '', `${fmt(ia.tokens_entrada)} tokens de entrada y ${fmt(ia.tokens_salida)} de salida`, 'dollar');
  const t = ia.test || [];
  const n = t[0]?.n;
  $('#ia-test-subtitle').textContent = n ? `${n} pacientes de prueba, con otra redacción de notas; los mismos para todos los métodos` : '';
  $('#ia-test').innerHTML = t.length ? `<thead><tr><th>Método</th><th>Empeoraron y los subió</th><th>Subió sin que empeoraran</th><th>Alta que quedó en baja</th></tr></thead><tbody>${t.map(r => `<tr class="${r.metodo === 'ia' ? 'fila-ia' : ''}"><td>${esc(NOMBRES_METODO[r.metodo] || r.metodo)}</td><td><b>${r.detectados}</b> de ${r.empeoraron}</td><td>${r.falsas_alarmas} de ${r.no_empeoraron}</td><td>${r.quedaron_en_baja} de ${r.debian_ser_alta}</td></tr>`).join('')}</tbody>` : '<tbody><tr><td>Sin medición todavía.</td></tr></tbody>';
  $('#ia-test-note').textContent = 'La verdad (riesgo real a 90 días) la conoce solo el mundo sintético; el agente nunca la ve. La validación real es con especialistas del hospital (κ, muestra ciega).';
  const ciclo = ia.ciclo || [];
  $('#ia-cycle').innerHTML = ciclo.map(c => `<div class="specialty-row cycle-row"><div class="specialty-row-top"><span>Iteración ${c.iteracion} · ${esc(c.version)}</span><strong>${fmt(c.dev_objetivo, 3)}</strong></div><small>${c.iteracion === 0 ? 'Rúbrica inicial escrita sin mirar la verdad' : c.aceptada ? 'Aceptada: mejoró en validación' : c.dev_objetivo_candidata != null ? `Rechazada: la candidata dio ${fmt(c.dev_objetivo_candidata, 3)} en validación` : 'Sin reglas que pasaran el filtro'}${c.cambios ? ' · «' + esc(String(c.cambios).slice(0, 140)) + '…»' : ''}</small></div>`).join('')
    + (ia.pertinencia ? `<div class="soft-note"><span>${icon('info')}</span><p>Pertinencia: de ${ia.pertinencia.no_relacionados} eventos que la regla considera no relacionados con la derivación, el agente declaró como descartados ${ia.pertinencia.descartados_por_ia}.</p></div>` : '');
  renderDecisiones();
}
function renderDecisiones() {
  const h = memoria.historial;
  $('#decisions-tag').textContent = `${h.length} decisiones`;
  $('#nav-ia-count').textContent = h.length || '';
  $('#decisions-list').innerHTML = h.length ? h.map(d => `<article class="history-event"><span class="event-mark">${icon(d.decision === 'revertida' ? 'undo' : d.decision === 'prioridad_absoluta' ? 'star' : 'check')}</span><div class="event-body"><h3><button class="patient-name" data-open-patient="${d.id_paciente}">${esc(d.nombre)}</button> · ${esc(d.decision.replace('ia_', '').replace('_', ' '))}</h3><p>${esc(d.usuario)} · ${esc(d.especialidad)} · propuesta IA #${d.antes} → #${d.despues}${d.motivo ? ' · ' + esc(d.motivo) : ''}</p></div><time class="event-time">${d.fecha_registro.slice(11, 16)}</time></article>`).join('')
    + '<div class="action-row padded"><button class="button secondary" id="clear-decisions">Borrar decisiones de este navegador</button></div>'
    : '<p class="empty-note">Todavía no hay decisiones. Ábrelas desde la ficha de un paciente.</p>';
  bindPatients($('#decisions-list'));
  const c = $('#clear-decisions');
  if (c) c.onclick = () => { memoria.decisiones = {}; memoria.absolutos = []; memoria.historial = []; guardarAlmacen(); POS = posiciones(); renderIA(); };
}

// ------------------------------------------------------------------------------------------- exportar
function descargar(nombre, filas) {
  const csv = '﻿' + filas.map(r => r.map(x => '"' + String(x ?? '').replace(/"/g, '""') + '"').join(';')).join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8'}));
  const a = document.createElement('a'); a.href = url; a.download = nombre; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ------------------------------------------------------------------------------------------- inicio
function perfilUI() {
  const pf = PERFILES[memoria.perfil];
  $('#profile-avatar').textContent = pf.corto;
  $('#profile-name').textContent = pf.nombre;
  $('#profile-switch small').textContent = `Cambiar a ${pf.otro}`;
}
function iniciar() {
  const m = D.meta;
  $('#next-update').textContent = `lunes ${fecha(m.proximo_corte)} · 07:00`;
  $('#intake-next-update').textContent = `lunes ${fecha(m.proximo_corte)} · 07:00`;
  $('#context-left').textContent = `Datos sintéticos del desafío · agente: ${D.ia?.modelo_nombre || 'sin propuestas'} en Amazon Bedrock`;
  $('#reference-date').textContent = `Lista vigente: corte del lunes ${fecha(m.corte)}`;
  $('#footer-right').textContent = `Regla ${m.version_regla} · datos al ${fecha(m.hoy)} · generado ${String(m.generado).replace('T', ' ').slice(0, 16)}`;
  $('#nav-list-count').textContent = P.length;
  $('#nav-alertas-count').textContent = (D.alertas?.items?.length) || '';
  $('#nav-intake-count').textContent = D.ingresos.length;
  $('#nav-ia-count').textContent = memoria.historial.length || '';
  const sobre = P.filter(p => p.sobre_p90).length, rev = P.filter(porRevisar).length;
  $('#list-summary').innerHTML = `<span><b>${P.length}</b> personas en la lista vigente</span><span class="summary-dot"></span><span><b>${sobre}</b> superan el umbral del 90% (${fmt(P90)} días)</span><span class="summary-dot"></span><button class="text-button" id="show-review">${icon('alert')}${rev} por revisar</button>`;
  $('#show-review').onclick = () => { state.filter = 'revisar'; state.listPage = 1; renderList(); };
  $('#specialty-filter').innerHTML += D.especialidades.map(e => `<option value="${esc(e.nombre)}">${esc(e.nombre)}</option>`).join('');
  $$('.nav-button[data-page]').forEach(b => { b.onclick = () => showPage(b.dataset.page); });
  $$('[data-goto]').forEach(b => { b.onclick = () => showPage(b.dataset.goto); });
  $('.logo').onclick = e => { e.preventDefault(); showPage('overview'); };
  $$('[data-filter]').forEach(b => { b.onclick = () => { state.filter = b.dataset.filter; state.listPage = 1; renderList(); }; });
  $$('[data-order]').forEach(b => { b.onclick = () => { state.order = b.dataset.order; state.listPage = 1; renderList(); }; });
  $('#patient-search').oninput = () => { state.listPage = 1; renderList(); };
  $('#specialty-filter').onchange = () => { state.listPage = 1; renderList(); };
  $('#previous-page').onclick = () => { state.listPage--; renderList(); };
  $('#next-page').onclick = () => { state.listPage++; renderList(); };
  $('#close-intake').onclick = () => $('#intake-dialog').close();
  $('#profile-switch').onclick = () => { memoria.perfil = memoria.perfil === 'jefe' ? 'gestora' : 'jefe'; guardarAlmacen(); perfilUI(); if (state.page === 'patient') renderPatient(); };
  $('#export-list').onclick = () => {
    const pos = state.order === 'ia' ? POS.ia : POS.regla;
    descargar(`lista_${state.order}_${m.corte}.csv`, [['puesto', 'especialidad', 'id_paciente', 'nombre', 'dias_espera', 'prioridad_inicial', 'prioridad_hoy', 'carril_rapido', 'propuesta_ia', 'puntaje_ia', 'estado'],
      ...filteredRows().map(p => [pos.get(p.id), p.especialidad, p.id, p.nombre, p.dias_espera, p.t1, prioridadVista(p), p.carril ? 'sí' : 'no', p.ia?.categoria, p.ia?.puntaje, estado(p)])]);
  };
  $('#export-decisions').onclick = () => descargar('decisiones_pulso.csv', [['fecha_registro', 'usuario', 'especialidad', 'id_paciente', 'decision', 'motivo', 'puesto_ia_antes', 'puesto_ia_despues'],
    ...memoria.historial.map(d => [d.fecha_registro, d.usuario, d.especialidad, d.id_paciente, d.decision, d.motivo, d.antes, d.despues])]);
  perfilUI();
  renderOverview();
  renderList();
  renderIntake();
  fillIcons();
  const hash = location.hash.replace('#', '');
  if (hash.startsWith('paciente=')) openPatient(decodeURIComponent(hash.slice(9)));
  else showPage(['list', 'alertas', 'intake', 'ia'].includes(hash) ? hash : 'overview', false);
}
iniciar();
