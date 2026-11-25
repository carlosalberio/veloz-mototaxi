const appShell = document.getElementById('app-shell');
const viewHeading = document.getElementById('view-heading');
const globalFeedback = document.getElementById('global-feedback');
const navButtons = [...document.querySelectorAll('[data-view-button]')];
const panels = [...document.querySelectorAll('[data-view]')];
const titles = {
  overview: 'Visão geral',
  rides: 'Minhas corridas',
  map: 'Mapa e GPS',
  finance: 'Ganhos',
  expenses: 'Despesas',
  reports: 'Relatórios',
  reviews: 'Avaliações',
  notifications: 'Notificações',
  profile: 'Meu perfil',
  settings: 'Configurações',
};
const labels = {
  solicitada: 'Solicitada',
  aceita: 'Aceita',
  em_andamento: 'Em andamento',
  concluida: 'Concluída',
  cancelada: 'Cancelada',
  pendente: 'Pendente',
  confirmado: 'Confirmado',
};
const currency = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
let ridePage = 1;
const ridePageSize = 20;
let rideTotal = 0;
let gpsWatchId = null;
let mapInstance = null;
let mapLine = null;
let mapMarker = null;
let lastGpsSentAt = 0;
let currentRide = null;

const setFeedback = (element, message, state = 'error') => {
  if (!(element instanceof HTMLElement)) return;
  element.textContent = message;
  element.dataset.state = state;
};

const notify = (message, state = 'error') => {
  if (!(globalFeedback instanceof HTMLElement)) return;
  globalFeedback.textContent = message;
  globalFeedback.dataset.state = state;
  globalFeedback.hidden = false;
  window.clearTimeout(notify.timeout);
  notify.timeout = window.setTimeout(() => {
    globalFeedback.hidden = true;
  }, 6500);
};

const request = async (path, options = {}) => {
  let response;
  try {
    const headers = { ...options.headers };
    if (typeof options.body === 'string') headers['Content-Type'] = 'application/json';
    response = await fetch(path, {
      ...options,
      credentials: 'same-origin',
      headers,
    });
  } catch {
    throw new Error('Não foi possível conectar ao servidor. Verifique a aplicação e tente novamente.');
  }

  let result = {};
  try {
    result = await response.json();
  } catch {
    result = {};
  }
  if (!response.ok) {
    const detail = result.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join(' ')
      : detail;
    const error = new Error(message || 'Não foi possível concluir a operação.');
    error.status = response.status;
    throw error;
  }
  return result;
};

const formatMoney = (cents) => currency.format((Number(cents) || 0) / 100);
const formatDistance = (meters) => `${((Number(meters) || 0) / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} km`;
const formatDate = (value, includeTime = true) => {
  if (!value) return '—';
  const parsed = /^\d{4}-\d{2}-\d{2}$/.test(String(value))
    ? new Date(`${value}T12:00:00`)
    : new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat('pt-BR', includeTime
    ? { dateStyle: 'short', timeStyle: 'short' }
    : { dateStyle: 'short' }).format(parsed);
};
const formatDuration = (seconds) => {
  if (seconds === null || seconds === undefined) return '—';
  const minutes = Math.max(0, Math.round(Number(seconds) / 60));
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}min`;
};
const make = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = String(text);
  return element;
};
const addCell = (row, value, className = '') => {
  const cell = row.insertCell();
  if (className) cell.className = className;
  cell.textContent = value === null || value === undefined ? '—' : String(value);
  return cell;
};
const statusBadge = (status) => {
  const badge = make('span', 'status-pill', labels[status] || status || '—');
  if (status === 'concluida' || status === 'confirmado') badge.classList.add('is-success');
  else if (status === 'cancelada') badge.classList.add('is-danger');
  else if (status === 'pendente' || status === 'solicitada') badge.classList.add('is-pending');
  else badge.classList.add('is-info');
  return badge;
};

const switchView = (viewName) => {
  panels.forEach((panel) => {
    const active = panel.dataset.view === viewName;
    panel.classList.toggle('is-visible', active);
    panel.hidden = !active;
  });
  navButtons.forEach((button) => {
    const active = button.dataset.viewButton === viewName;
    button.classList.toggle('is-active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  if (viewHeading) viewHeading.textContent = titles[viewName] || 'Painel';
  appShell?.classList.remove('mobile-nav-open');
  const menuButton = document.getElementById('mobile-menu');
  menuButton?.setAttribute('aria-expanded', 'false');
  const loaders = {
    overview: loadDashboard,
    rides: loadRidesView,
    map: loadMapView,
    finance: loadFinance,
    expenses: loadExpenses,
    reports: () => {},
    reviews: loadReviews,
    notifications: loadNotifications,
    profile: loadProfile,
    settings: () => {},
  };
  const loadView = loaders[viewName];
  if (loadView) Promise.resolve(loadView()).catch((error) => notify(error.message));
};

navButtons.forEach((button) => {
  button.addEventListener('click', () => switchView(button.dataset.viewButton));
});

const renderChart = (items) => {
  const container = document.getElementById('earnings-chart');
  const empty = document.getElementById('chart-empty');
  if (!(container instanceof HTMLElement)) return;
  container.replaceChildren();
  if (!items.length || !items.some((item) => item.paid_cents || item.expenses_cents)) {
    if (empty) empty.hidden = false;
    return;
  }
  if (empty) empty.hidden = true;
  const namespace = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(namespace, 'svg');
  const width = Math.max(540, items.length * 38);
  const height = 220;
  const left = 34;
  const bottom = 25;
  const chartHeight = 165;
  const max = Math.max(1, ...items.flatMap((item) => [item.paid_cents, item.expenses_cents]));
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Ganhos confirmados e despesas por dia');

  [0, 0.5, 1].forEach((ratio) => {
    const y = 8 + chartHeight * ratio;
    const line = document.createElementNS(namespace, 'line');
    line.setAttribute('x1', String(left));
    line.setAttribute('x2', String(width - 6));
    line.setAttribute('y1', String(y));
    line.setAttribute('y2', String(y));
    line.setAttribute('class', 'chart-gridline');
    svg.append(line);
  });
  const slot = (width - left - 12) / items.length;
  const barWidth = Math.max(3, Math.min(12, slot * 0.28));
  items.forEach((item, index) => {
    const center = left + slot * (index + 0.5);
    [
      { key: 'paid_cents', className: 'chart-bar-paid', shift: -barWidth / 2 },
      { key: 'expenses_cents', className: 'chart-bar-expense', shift: barWidth / 2 + 1 },
    ].forEach((bar) => {
      const value = Number(item[bar.key]) || 0;
      const rect = document.createElementNS(namespace, 'rect');
      const barHeight = (value / max) * chartHeight;
      rect.setAttribute('x', String(center + bar.shift));
      rect.setAttribute('y', String(8 + chartHeight - barHeight));
      rect.setAttribute('width', String(barWidth));
      rect.setAttribute('height', String(Math.max(value ? 1 : 0, barHeight)));
      rect.setAttribute('rx', '2');
      rect.setAttribute('class', bar.className);
      rect.setAttribute('aria-label', `${item.date}: ${formatMoney(value)}`);
      svg.append(rect);
    });
    const label = document.createElementNS(namespace, 'text');
    label.setAttribute('x', String(center));
    label.setAttribute('y', String(height - 6));
    label.setAttribute('text-anchor', 'middle');
    label.textContent = item.date.slice(5);
    svg.append(label);
  });
  container.append(svg);
};

const loadDashboard = async () => {
  const period = document.getElementById('dashboard-period')?.value || '7dias';
  const data = await request(`/api/driver/dashboard?period=${encodeURIComponent(period)}`);
  const metrics = data.metrics;
  const values = {
    'metric-paid': formatMoney(metrics.confirmed_earnings_cents),
    'metric-pending': formatMoney(metrics.pending_payments_cents),
    'metric-completed': metrics.completed_rides,
    'metric-requested-label': `${metrics.requested_rides} solicitações no período`,
    'metric-distance': formatDistance(metrics.gps_distance_m),
    'metric-expenses': formatMoney(metrics.expenses_cents),
    'metric-net': formatMoney(metrics.net_cents),
    'metric-online': formatDuration(metrics.online_seconds),
    'metric-acceptance': metrics.acceptance_rate === null
      ? '—'
      : `${Math.round(metrics.acceptance_rate * 100)}%`,
    'metric-cancellation': metrics.cancellation_rate === null
      ? '—'
      : `${Math.round(metrics.cancellation_rate * 100)}%`,
    'metric-cancelled': `${metrics.cancelled_rides} corridas canceladas`,
    'metric-ticket': metrics.average_ticket_cents === null
      ? '—'
      : formatMoney(metrics.average_ticket_cents),
    'metric-hourly': metrics.earnings_per_online_hour_cents === null
      ? '—'
      : formatMoney(metrics.earnings_per_online_hour_cents),
    'metric-duration': formatDuration(metrics.average_duration_seconds),
    'metric-rating': metrics.average_rating === null
      ? '—'
      : `★ ${Number(metrics.average_rating).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}`,
    'metric-rating-count': `${metrics.rating_count} ${metrics.rating_count === 1 ? 'avaliação' : 'avaliações'}`,
    'metric-estimated-distance': metrics.estimated_distance_km === null
      ? 'Sem dados'
      : `${Number(metrics.estimated_distance_km).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} km`,
  };
  Object.entries(values).forEach(([id, value]) => {
    const target = document.getElementById(id);
    if (target) target.textContent = String(value);
  });
  renderChart(data.chart || []);
  await loadGoals();
};

const loadGoals = async () => {
  const result = await request('/api/driver/goals');
  const list = document.getElementById('goal-list');
  if (!(list instanceof HTMLElement)) return;
  list.replaceChildren();
  const periodQuery = { diaria: 'hoje', semanal: '7dias', mensal: '30dias' };
  const dashboards = await Promise.all(
    result.goals.map((goal) => request(`/api/driver/dashboard?period=${periodQuery[goal.period]}`)),
  );
  result.goals.forEach((goal, index) => {
    const metrics = dashboards[index].metrics;
    const row = make('div', 'goal-row');
    const copy = make('div', 'goal-copy');
    copy.append(
      make('span', '', goal.period[0].toUpperCase() + goal.period.slice(1)),
      make('strong', '', [
        goal.target_cents === null ? '' : formatMoney(goal.target_cents),
        goal.target_rides === null ? '' : `${goal.target_rides} corridas`,
      ].filter(Boolean).join(' · ')),
    );
    const progressValues = [];
    if (goal.target_cents > 0) progressValues.push(metrics.confirmed_earnings_cents / goal.target_cents);
    if (goal.target_rides > 0) progressValues.push(metrics.completed_rides / goal.target_rides);
    const percent = progressValues.length ? Math.min(100, Math.round(Math.min(...progressValues) * 100)) : 0;
    const progress = make('div', 'goal-progress');
    progress.setAttribute('role', 'progressbar');
    progress.setAttribute('aria-label', `Progresso da meta ${goal.period}`);
    progress.setAttribute('aria-valuemin', '0');
    progress.setAttribute('aria-valuemax', '100');
    progress.setAttribute('aria-valuenow', String(percent));
    const fill = make('span', 'goal-progress-fill');
    fill.style.width = `${percent}%`;
    progress.append(fill);
    row.append(copy, progress, make('small', 'goal-progress-label', `${percent}%`));
    list.append(row);
  });
};

document.getElementById('dashboard-period')?.addEventListener('change', () => {
  loadDashboard().catch((error) => notify(error.message));
});

document.getElementById('goal-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const amount = document.getElementById('goal-amount');
  const rides = document.getElementById('goal-rides');
  const feedback = document.getElementById('goal-feedback');
  const amountValue = amount instanceof HTMLInputElement && amount.value !== ''
    ? Math.round(Number(amount.value) * 100)
    : null;
  const ridesValue = rides instanceof HTMLInputElement && rides.value !== ''
    ? Number(rides.value)
    : null;
  try {
    await request('/api/driver/goals', {
      method: 'PUT',
      body: JSON.stringify({
        period: document.getElementById('goal-period').value,
        target_cents: amountValue,
        target_rides: ridesValue,
      }),
    });
    setFeedback(feedback, 'Meta salva.', 'success');
    await loadGoals();
  } catch (error) {
    setFeedback(feedback, error.message);
  }
});

const rideStatusFilter = document.getElementById('ride-status-filter');
const escapeText = (value) => String(value ?? '');
const createActionButton = (label, action, id, className = 'secondary-button small-button') => {
  const button = make('button', className, label);
  button.type = 'button';
  button.dataset.action = action;
  button.dataset.id = String(id);
  return button;
};

const loadAvailableRides = async () => {
  const result = await request('/api/driver/rides/available');
  const list = document.getElementById('available-rides');
  if (!(list instanceof HTMLElement)) return;
  list.replaceChildren();
  if (!result.rides.length) {
    list.append(make('p', 'empty-note', 'Nenhuma solicitação disponível agora.'));
    return;
  }
  result.rides.forEach((ride) => {
    const isOrder = ride.service_type === 'pedido';
    const card = make('article', 'available-ride');
    card.dataset.serviceType = ride.service_type || 'passageiro';

    const route = make('div');
    const title = make('strong', 'available-ride-title');
    title.textContent = isOrder ? '📦 Nova corrida — Pedido' : '👤 Nova corrida — Passageiro';

    const pickupLine = make('span', 'available-ride-point');
    pickupLine.append(
      make('small', '', isOrder ? 'Retirada: ' : 'Origem: '),
      document.createTextNode(ride.pickup),
    );

    const destLine = make('span', 'available-ride-point');
    destLine.append(
      make('small', '', isOrder ? 'Entrega: ' : 'Destino: '),
      document.createTextNode(ride.destination),
    );

    const metaLine = make('span', 'available-ride-meta', `Código #${ride.code} · ${formatDate(ride.created_at)}`);

    route.append(title, pickupLine, destLine, metaLine);

    const payment = make('div');
    payment.append(
      make('strong', '', formatMoney(ride.amount_cents)),
      make('span', '', `Pagamento: ${ride.payment_method} · pendente após conclusão`),
    );
    const actions = make('div', 'available-ride-actions');
    actions.append(
      createActionButton('Aceitar', 'accept', ride.id, 'primary-button small-button'),
      createActionButton('Recusar', 'decline', ride.id),
    );
    card.append(route, payment, actions);
    list.append(card);
  });
};

const loadRides = async () => {
  const status = rideStatusFilter instanceof HTMLSelectElement ? rideStatusFilter.value : '';
  const params = new URLSearchParams({ page: String(ridePage), page_size: String(ridePageSize) });
  if (status) params.set('status', status);
  const result = await request(`/api/driver/rides?${params}`);
  rideTotal = result.total;
  const body = document.getElementById('ride-table-body');
  const label = document.getElementById('ride-pagination-label');
  const previous = document.getElementById('rides-prev');
  const next = document.getElementById('rides-next');
  if (!(body instanceof HTMLTableSectionElement)) return;
  body.replaceChildren();
  if (!result.rides.length) {
    const row = body.insertRow();
    addCell(row, 'Nenhuma corrida registrada neste período.', 'empty-cell').colSpan = 5;
  }
  result.rides.forEach((ride) => {
    const isOrder = ride.service_type === 'pedido';
    const row = body.insertRow();
    const code = row.insertCell();
    const serviceBadge = make('span', `service-badge ${isOrder ? 'badge-pedido' : 'badge-passageiro'}`, isOrder ? '📦 Pedido' : '👤 Passageiro');
    code.append(
      serviceBadge,
      make('strong', '', `#${ride.code}`),
      make('small', '', formatDate(ride.created_at)),
    );
    const routeCell = row.insertCell();
    routeCell.append(
      make('span', '', `${ride.pickup} → ${ride.destination}`),
      make('small', '', isOrder ? 'Retirada → Entrega' : 'Origem → Destino'),
    );
    const payment = row.insertCell();
    payment.append(make('strong', '', formatMoney(ride.amount_cents)), make('small', '', `${ride.payment_method} · ${labels[ride.payment_status] || ride.payment_status}`));
    const status = row.insertCell();
    status.append(statusBadge(ride.status));
    const actions = row.insertCell();
    const actionWrap = make('div', 'button-row');
    actionWrap.append(createActionButton('Detalhes', 'details', ride.id));
    if (ride.status === 'aceita') actionWrap.append(createActionButton('Iniciar', 'start', ride.id, 'primary-button small-button'));
    if (ride.status === 'em_andamento') actionWrap.append(createActionButton('Concluir', 'complete', ride.id, 'primary-button small-button'));
    if (ride.status === 'aceita' || ride.status === 'em_andamento') actionWrap.append(createActionButton('Cancelar', 'cancel', ride.id));
    actions.append(actionWrap);
  });
  const first = result.total ? ((ridePage - 1) * ridePageSize) + 1 : 0;
  if (label) label.textContent = `${first}–${Math.min(ridePage * ridePageSize, result.total)} de ${result.total}`;
  if (previous instanceof HTMLButtonElement) previous.disabled = ridePage <= 1;
  if (next instanceof HTMLButtonElement) next.disabled = ridePage * ridePageSize >= result.total;
};

const loadRidesView = async () => {
  await Promise.all([loadAvailableRides(), loadRides()]);
};

const showRideDetails = async (rideId) => {
  const ride = await request(`/api/driver/rides/${rideId}`);
  const content = document.getElementById('ride-dialog-content');
  const title = document.getElementById('ride-dialog-title');
  if (!(content instanceof HTMLElement) || !(title instanceof HTMLElement)) return;
  const isOrder = ride.service_type === 'pedido';
  title.textContent = isOrder ? `Pedido #${ride.code}` : `Corrida #${ride.code}`;
  content.replaceChildren();
  const values = [
    ['Tipo de serviço', isOrder ? '📦 Pedido (transporte de objetos)' : '👤 Passageiro (transporte de pessoas)'],
    ['Status', labels[ride.status] || ride.status],
    [isOrder ? 'Solicitante' : 'Passageiro', ride.passenger_name],
    ['Celular', ride.passenger_phone],
    [isOrder ? 'Endereço de retirada' : 'Origem', ride.pickup],
    [isOrder ? 'Endereço de entrega' : 'Destino', ride.destination],
    ['Agendada para', formatDate(ride.scheduled_at)],
    ['Forma de pagamento', ride.payment_method],
    ['Situação do pagamento', labels[ride.payment_status] || ride.payment_status],
    ['Distância via GPS', formatDistance(ride.gps_distance_m)],
    ['Duração registrada', formatDuration(ride.duration_seconds)],
  ];
  const fields = make('div', 'dialog-fields');
  values.forEach(([label, value]) => {
    const field = make('div', 'dialog-field');
    field.append(make('span', '', label), make('strong', '', escapeText(value)));
    fields.append(field);
  });
  content.append(fields);
  const dialog = document.getElementById('ride-dialog');
  if (dialog instanceof HTMLDialogElement && !dialog.open) dialog.showModal();
};

document.getElementById('available-rides')?.addEventListener('click', async (event) => {
  const target = event.target instanceof Element ? event.target.closest('[data-action]') : null;
  if (!(target instanceof HTMLButtonElement)) return;
  const rideId = target.dataset.id;
  try {
    await request(`/api/driver/rides/${rideId}/${target.dataset.action}`, { method: 'POST' });
    notify(target.dataset.action === 'accept' ? 'Solicitação aceita e vinculada à sua conta.' : 'Oferta recusada.', 'success');
    await loadRidesView();
  } catch (error) {
    notify(error.message);
  }
});

document.getElementById('ride-table-body')?.addEventListener('click', async (event) => {
  const target = event.target instanceof Element ? event.target.closest('[data-action]') : null;
  if (!(target instanceof HTMLButtonElement)) return;
  const rideId = target.dataset.id;
  try {
    if (target.dataset.action === 'details') {
      await showRideDetails(rideId);
      return;
    }
    const transition = {
      start: 'em_andamento',
      complete: 'concluida',
      cancel: 'cancelada',
    }[target.dataset.action];
    if (target.dataset.action === 'cancel' && !window.confirm('Deseja cancelar esta corrida?')) return;
    await request(`/api/driver/rides/${rideId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status: transition }),
    });
    notify(
      transition === 'concluida'
        ? 'Serviço concluído. O pagamento continua pendente até confirmação.'
        : 'Status atualizado.',
      'success',
    );
    if (currentRide === String(rideId) && transition !== 'em_andamento') {
      stopGpsTracking('Corrida encerrada; rastreamento GPS parado.');
    }
    await loadRidesView();
    await loadMapView();
  } catch (error) {
    notify(error.message);
  }
});

rideStatusFilter?.addEventListener('change', () => {
  ridePage = 1;
  loadRides().catch((error) => notify(error.message));
});
document.getElementById('refresh-rides')?.addEventListener('click', () => {
  loadRidesView().catch((error) => notify(error.message));
});
document.getElementById('rides-prev')?.addEventListener('click', () => {
  if (ridePage > 1) ridePage -= 1;
  loadRides().catch((error) => notify(error.message));
});
document.getElementById('rides-next')?.addEventListener('click', () => {
  if (ridePage * ridePageSize < rideTotal) ridePage += 1;
  loadRides().catch((error) => notify(error.message));
});
document.getElementById('ride-dialog-close')?.addEventListener('click', () => {
  const dialog = document.getElementById('ride-dialog');
  if (dialog instanceof HTMLDialogElement) dialog.close();
});

const initMap = () => {
  const mapElement = document.getElementById('ride-map');
  if (!(mapElement instanceof HTMLElement) || mapInstance) return;
  if (!window.L) {
    mapElement.textContent = 'O mapa não foi carregado. Verifique a conexão para visualizar os mapas OpenStreetMap.';
    mapElement.classList.add('map-unavailable');
    return;
  }
  const serviceAreaBounds = window.L.latLngBounds(
    [-8.4385, -38.6276],
    [-7.6784, -38.0282],
  );
  mapInstance = window.L.map(mapElement, {
    maxBounds: serviceAreaBounds,
    maxBoundsViscosity: 0.8,
  }).setView([-7.9867805, -38.2920294], 13);
  window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(mapInstance);
};

const loadRoute = async (rideId) => {
  if (!rideId) {
    setFeedback(document.getElementById('gps-feedback'), 'Selecione uma corrida para consultar o trajeto.');
    return;
  }
  const result = await request(`/api/driver/rides/${rideId}/gps`);
  initMap();
  if (!mapInstance) {
    setFeedback(document.getElementById('gps-feedback'), 'O mapa externo não está disponível nesta conexão.');
    return;
  }
  if (mapLine) mapLine.remove();
  if (mapMarker) mapMarker.remove();
  const coordinates = result.points.map((point) => [point.latitude, point.longitude]);
  if (coordinates.length) {
    mapLine = window.L.polyline(coordinates, { color: '#315b39', weight: 5, opacity: 0.82 }).addTo(mapInstance);
    mapMarker = window.L.circleMarker(coordinates[coordinates.length - 1], {
      radius: 7,
      color: '#fff',
      weight: 2,
      fillColor: '#e8753d',
      fillOpacity: 1,
    }).addTo(mapInstance);
    mapInstance.fitBounds(mapLine.getBounds(), { padding: [24, 24] });
    setFeedback(
      document.getElementById('gps-feedback'),
      `${coordinates.length} pontos registrados · distância aproximada ${formatDistance(result.distance_m)}.`,
      'success',
    );
  } else {
    setFeedback(document.getElementById('gps-feedback'), 'Esta corrida ainda não possui pontos GPS registrados.');
  }
};

const loadMapView = async () => {
  initMap();
  const [result, history] = await Promise.all([
    request('/api/driver/rides?status=em_andamento&page=1&page_size=100'),
    request('/api/driver/rides?status=concluida&page=1&page_size=100'),
  ]);
  const select = document.getElementById('gps-ride-select');
  if (select instanceof HTMLSelectElement) {
    const selected = select.value;
    select.replaceChildren(new Option('Nenhuma corrida ativa', ''));
    result.rides.forEach((ride) => {
      select.add(new Option(`${ride.code} · ${ride.pickup} → ${ride.destination}`, String(ride.id)));
    });
    if (result.rides.some((ride) => String(ride.id) === selected)) select.value = selected;
    else if (result.rides.length) select.value = String(result.rides[0].id);
    const start = document.getElementById('gps-start');
    if (start instanceof HTMLButtonElement) {
      start.disabled = !select.value || !document.getElementById('gps-consent')?.checked || gpsWatchId !== null;
    }
  }
  const historySelect = document.getElementById('gps-history-select');
  if (historySelect instanceof HTMLSelectElement) {
    const selected = historySelect.value;
    historySelect.replaceChildren(new Option('Selecione uma corrida concluída', ''));
    history.rides.forEach((ride) => {
      historySelect.add(new Option(`${ride.code} · ${formatDate(ride.completed_at || ride.created_at, false)}`, String(ride.id)));
    });
    if (history.rides.some((ride) => String(ride.id) === selected)) historySelect.value = selected;
  }
};

const stopGpsTracking = (message = 'Rastreamento GPS parado.') => {
  if (gpsWatchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(gpsWatchId);
  gpsWatchId = null;
  currentRide = null;
  const start = document.getElementById('gps-start');
  const stop = document.getElementById('gps-stop');
  const select = document.getElementById('gps-ride-select');
  if (select instanceof HTMLSelectElement) select.disabled = false;
  if (start instanceof HTMLButtonElement) {
    start.disabled = !(select instanceof HTMLSelectElement && select.value && document.getElementById('gps-consent')?.checked);
  }
  if (stop instanceof HTMLButtonElement) stop.disabled = true;
  setFeedback(document.getElementById('gps-feedback'), message, 'success');
};

document.getElementById('gps-consent')?.addEventListener('change', () => {
  const start = document.getElementById('gps-start');
  const select = document.getElementById('gps-ride-select');
  if (start instanceof HTMLButtonElement) {
    start.disabled = !(select instanceof HTMLSelectElement && select.value && document.getElementById('gps-consent').checked) || gpsWatchId !== null;
  }
});
document.getElementById('gps-ride-select')?.addEventListener('change', () => {
  const select = document.getElementById('gps-ride-select');
  const start = document.getElementById('gps-start');
  if (start instanceof HTMLButtonElement) {
    start.disabled = !(select instanceof HTMLSelectElement && select.value && document.getElementById('gps-consent')?.checked) || gpsWatchId !== null;
  }
});
document.getElementById('gps-start')?.addEventListener('click', () => {
  const feedback = document.getElementById('gps-feedback');
  const rideSelect = document.getElementById('gps-ride-select');
  const consent = document.getElementById('gps-consent');
  if (!(rideSelect instanceof HTMLSelectElement) || !rideSelect.value) {
    setFeedback(feedback, 'Selecione uma corrida em andamento.');
    return;
  }
  if (!(consent instanceof HTMLInputElement) || !consent.checked) {
    setFeedback(feedback, 'Marque o consentimento antes de ativar o GPS.');
    return;
  }
  if (!navigator.geolocation) {
    setFeedback(feedback, 'Este navegador não oferece geolocalização.');
    return;
  }
  currentRide = rideSelect.value;
  gpsWatchId = navigator.geolocation.watchPosition(async (position) => {
    const accuracy = position.coords.accuracy;
    if (accuracy > 100) {
      setFeedback(feedback, 'Precisão do GPS acima de 100 m; este ponto não será enviado.');
      return;
    }
    if (Date.now() - lastGpsSentAt < 5000) return;
    lastGpsSentAt = Date.now();
    try {
      const result = await request(`/api/driver/rides/${currentRide}/gps`, {
        method: 'POST',
        body: JSON.stringify({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy_m: accuracy,
          recorded_at: new Date(position.timestamp).toISOString(),
        }),
      });
      setFeedback(feedback, `GPS ativo · distância registrada ${formatDistance(result.distance_m)}.`, 'success');
    } catch (error) {
      if (error.status === 409) stopGpsTracking('A corrida não está mais em andamento; rastreamento encerrado.');
      else if (error.status === 422) {
        stopGpsTracking();
        setFeedback(feedback, error.message);
      } else setFeedback(feedback, error.message);
    }
  }, (error) => {
    const messages = {
      1: 'Permissão de localização negada. Autorize o acesso no navegador para compartilhar o GPS.',
      2: 'Não foi possível obter sua localização.',
      3: 'A solicitação de localização expirou. Tente novamente.',
    };
    stopGpsTracking(messages[error.code] || 'Falha ao obter localização.');
  }, {
    enableHighAccuracy: true,
    maximumAge: 3000,
    timeout: 15000,
  });
  const start = document.getElementById('gps-start');
  const stop = document.getElementById('gps-stop');
  const select = document.getElementById('gps-ride-select');
  if (start instanceof HTMLButtonElement) start.disabled = true;
  if (stop instanceof HTMLButtonElement) stop.disabled = false;
  if (select instanceof HTMLSelectElement) select.disabled = true;
  setFeedback(feedback, 'Rastreamento iniciado. A localização só será enviada durante esta corrida.', 'success');
});
document.getElementById('gps-stop')?.addEventListener('click', () => stopGpsTracking());
document.getElementById('gps-load-route')?.addEventListener('click', () => {
  const historySelect = document.getElementById('gps-history-select');
  const select = document.getElementById('gps-ride-select');
  const rideId = historySelect instanceof HTMLSelectElement && historySelect.value
    ? historySelect.value
    : select instanceof HTMLSelectElement
      ? select.value
      : '';
  if (historySelect instanceof HTMLSelectElement) historySelect.value = rideId;
  loadRoute(rideId).catch((error) => notify(error.message));
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden && gpsWatchId !== null) {
    stopGpsTracking('Rastreamento encerrado ao sair desta página; ele não funciona em segundo plano.');
  }
  if (document.hidden && deliveryGpsWatchId !== null) {
    stopDeliveryGps('Rastreamento da entrega encerrado ao sair desta página; ele não funciona em segundo plano.');
  }
});

const renderAvailability = (online) => {
  const wrap = document.querySelector('.availability-wrap');
  const label = document.getElementById('availability-label');
  const button = document.getElementById('availability-toggle');
  if (wrap) wrap.classList.toggle('is-online', online);
  if (label) label.textContent = online ? 'Online' : 'Offline';
  if (button instanceof HTMLButtonElement) {
    button.textContent = online ? 'Ficar offline' : 'Ficar online';
    button.setAttribute('aria-pressed', String(online));
  }
};

const refreshAvailability = async () => {
  const result = await request('/api/driver/availability');
  renderAvailability(result.online);
  return result.online;
};

document.getElementById('availability-toggle')?.addEventListener('click', async () => {
  const button = document.getElementById('availability-toggle');
  const online = button?.getAttribute('aria-pressed') !== 'true';
  if (button instanceof HTMLButtonElement) button.disabled = true;
  try {
    const result = await request('/api/driver/availability', {
      method: 'PUT',
      body: JSON.stringify({ online }),
    });
    renderAvailability(result.online);
    notify(result.online ? 'Você está online e pode receber solicitações.' : 'Você está offline.', 'success');
    if (result.online) await loadAvailableRides();
  } catch (error) {
    notify(error.message);
    await refreshAvailability().catch(() => {});
  } finally {
    if (button instanceof HTMLButtonElement) button.disabled = false;
  }
});

document.getElementById('finance-period')?.addEventListener('change', () => {
  loadFinance().catch((error) => notify(error.message));
});

const loadFinance = async () => {
  const period = document.getElementById('finance-period')?.value || '30dias';
  const days = period === '7dias' ? 7 : 30;
  const end = new Date();
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - days + 1);
  const params = new URLSearchParams({ from: start.toISOString().slice(0, 10), to: end.toISOString().slice(0, 10), status: 'concluida', page_size: '100' });
  const [dashboard, rides, deliveryResult] = await Promise.all([
    request(`/api/driver/dashboard?period=${period}`),
    request(`/api/driver/rides?${params}`),
    request('/api/driver/deliveries'),
  ]);
  const metrics = dashboard.metrics;
  [
    ['finance-paid', formatMoney(metrics.confirmed_earnings_cents)],
    ['finance-pending', formatMoney(metrics.pending_payments_cents)],
    ['finance-expenses', formatMoney(metrics.expenses_cents)],
    ['finance-net', formatMoney(metrics.net_cents)],
  ].forEach(([id, value]) => {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  });
  const body = document.getElementById('finance-table-body');
  if (!(body instanceof HTMLTableSectionElement)) return;
  body.replaceChildren();
  if (!rides.rides.length) {
    const row = body.insertRow();
    addCell(row, 'Nenhuma corrida concluída neste período.', 'empty-cell').colSpan = 5;
  }
  rides.rides.forEach((ride) => {
    const row = body.insertRow();
    addCell(row, `#${ride.code}`);
    addCell(row, formatDate(ride.completed_at || ride.created_at));
    addCell(row, ride.payment_method);
    addCell(row, formatMoney(ride.amount_cents));
    row.insertCell().append(statusBadge(ride.payment_status));
  });
  const completedDeliveries = deliveryResult.deliveries.filter((delivery) => (
    delivery.status === 'entregue'
    && delivery.delivered_at
    && delivery.delivered_at.slice(0, 10) >= start.toISOString().slice(0, 10)
    && delivery.delivered_at.slice(0, 10) <= end.toISOString().slice(0, 10)
  ));
  const deliveryTotal = completedDeliveries.reduce((sum, delivery) => sum + delivery.amount_cents, 0);
  const deliveryPending = completedDeliveries
    .filter((delivery) => delivery.payment_status !== 'confirmado')
    .reduce((sum, delivery) => sum + delivery.amount_cents, 0);
  [
    ['finance-delivery-count', String(completedDeliveries.length)],
    ['finance-delivery-total', formatMoney(deliveryTotal)],
    ['finance-delivery-pending', formatMoney(deliveryPending)],
    ['finance-delivery-confirmed', formatMoney(deliveryTotal - deliveryPending)],
  ].forEach(([id, value]) => {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  });
  const deliveryBody = document.getElementById('finance-delivery-table-body');
  if (deliveryBody instanceof HTMLTableSectionElement) {
    deliveryBody.replaceChildren();
    if (!completedDeliveries.length) {
      const row = deliveryBody.insertRow();
      addCell(row, 'Nenhuma entrega concluída neste período.', 'empty-cell').colSpan = 5;
    }
    completedDeliveries.forEach((delivery) => {
      const row = deliveryBody.insertRow();
      addCell(row, `#${delivery.code}`);
      addCell(row, formatDate(delivery.delivered_at));
      addCell(row, delivery.category);
      addCell(row, formatMoney(delivery.amount_cents));
      row.insertCell().append(statusBadge(delivery.payment_status));
    });
  }
};

const loadExpenses = async () => {
  const result = await request('/api/driver/expenses');
  const body = document.getElementById('expense-table-body');
  if (!(body instanceof HTMLTableSectionElement)) return;
  body.replaceChildren();
  if (!result.expenses.length) {
    const row = body.insertRow();
    addCell(row, 'Nenhuma despesa registrada nos últimos 30 dias.', 'empty-cell').colSpan = 4;
  }
  result.expenses.forEach((expense) => {
    const row = body.insertRow();
    const dateCategory = row.insertCell();
    dateCategory.append(make('strong', '', formatDate(expense.spent_on, false)), make('small', '', expense.category));
    addCell(row, expense.description);
    addCell(row, formatMoney(expense.amount_cents));
    const actions = row.insertCell();
    actions.append(
      createActionButton('Editar', 'edit-expense', expense.id),
      createActionButton('Excluir', 'delete-expense', expense.id),
    );
  });
};

const clearExpenseForm = () => {
  const form = document.getElementById('expense-form');
  const id = document.getElementById('expense-id');
  const title = document.getElementById('expense-form-title');
  const submit = document.getElementById('expense-submit');
  const cancel = document.getElementById('expense-cancel-edit');
  if (form instanceof HTMLFormElement) form.reset();
  if (id instanceof HTMLInputElement) id.value = '';
  if (title) title.textContent = 'Adicionar despesa';
  if (submit) submit.textContent = 'Salvar despesa';
  if (cancel instanceof HTMLButtonElement) cancel.hidden = true;
  const dateInput = document.getElementById('expense-date');
  if (dateInput instanceof HTMLInputElement) dateInput.value = new Date().toISOString().slice(0, 10);
};

document.getElementById('expense-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const expenseId = document.getElementById('expense-id');
  const value = Number(document.getElementById('expense-amount').value);
  const feedback = document.getElementById('expense-feedback');
  if (!Number.isFinite(value) || value <= 0) {
    setFeedback(feedback, 'Informe um valor maior que zero.');
    return;
  }
  const payload = {
    category: document.getElementById('expense-category').value,
    description: document.getElementById('expense-description').value.trim(),
    amount_cents: Math.round(value * 100),
    spent_on: document.getElementById('expense-date').value,
  };
  const updating = expenseId instanceof HTMLInputElement && Boolean(expenseId.value);
  try {
    await request(updating ? `/api/driver/expenses/${expenseId.value}` : '/api/driver/expenses', {
      method: updating ? 'PUT' : 'POST',
      body: JSON.stringify(payload),
    });
    setFeedback(feedback, updating ? 'Despesa atualizada.' : 'Despesa registrada.', 'success');
    clearExpenseForm();
    await Promise.all([loadExpenses(), loadDashboard()]);
  } catch (error) {
    setFeedback(feedback, error.message);
  }
});

document.getElementById('expense-table-body')?.addEventListener('click', async (event) => {
  const target = event.target instanceof Element ? event.target.closest('[data-action]') : null;
  if (!(target instanceof HTMLButtonElement)) return;
  try {
    if (target.dataset.action === 'delete-expense') {
      if (!window.confirm('Deseja excluir esta despesa?')) return;
      await request(`/api/driver/expenses/${target.dataset.id}`, { method: 'DELETE' });
      notify('Despesa excluída.', 'success');
      await Promise.all([loadExpenses(), loadDashboard()]);
      return;
    }
    const { expenses } = await request('/api/driver/expenses');
    const expense = expenses.find((item) => String(item.id) === target.dataset.id);
    if (!expense) throw new Error('Despesa não encontrada para edição.');
    document.getElementById('expense-id').value = String(expense.id);
    document.getElementById('expense-category').value = expense.category;
    document.getElementById('expense-description').value = expense.description;
    document.getElementById('expense-amount').value = (expense.amount_cents / 100).toFixed(2);
    document.getElementById('expense-date').value = expense.spent_on;
    document.getElementById('expense-form-title').textContent = 'Editar despesa';
    document.getElementById('expense-submit').textContent = 'Salvar alterações';
    document.getElementById('expense-cancel-edit').hidden = false;
    document.getElementById('expense-description').focus();
  } catch (error) {
    notify(error.message);
  }
});

document.getElementById('expense-cancel-edit')?.addEventListener('click', clearExpenseForm);
document.getElementById('report-form')?.addEventListener('submit', (event) => {
  event.preventDefault();
  const format = event.submitter?.dataset.format;
  if (format !== 'csv' && format !== 'pdf') return;
  const params = new URLSearchParams({ kind: document.getElementById('report-kind').value });
  const start = document.getElementById('report-from').value;
  const end = document.getElementById('report-to').value;
  if (start) params.set('from', start);
  if (end) params.set('to', end);
  window.location.assign(`/api/driver/reports.${format}?${params}`);
});

const loadReviews = async () => {
  const result = await request('/api/driver/reviews');
  const average = document.getElementById('rating-average');
  const total = document.getElementById('rating-total');
  const stars = document.getElementById('rating-stars');
  const distribution = document.getElementById('rating-distribution');
  const list = document.getElementById('review-list');
  if (average) average.textContent = result.average === null
    ? 'Sem avaliações'
    : Number(result.average).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  if (total) total.textContent = `${result.total} ${result.total === 1 ? 'avaliação' : 'avaliações'}`;
  if (stars) stars.textContent = result.average === null ? '—' : '★'.repeat(Math.round(result.average));
  if (distribution instanceof HTMLElement) {
    distribution.replaceChildren();
    for (let score = 5; score >= 1; score -= 1) {
      const count = result.distribution[String(score)] || 0;
      const line = make('div', 'distribution-row');
      line.append(make('span', '', `${score} ★`));
      const track = make('div', 'distribution-track');
      const fill = make('div', 'distribution-fill');
      fill.style.width = `${result.total ? (count / result.total) * 100 : 0}%`;
      track.append(fill);
      line.append(track, make('span', '', count));
      distribution.append(line);
    }
  }
  if (!(list instanceof HTMLElement)) return;
  list.replaceChildren();
  if (!result.reviews.length) {
    list.append(make('p', 'empty-note', 'Ainda não há avaliações de corridas concluídas.'));
    return;
  }
  result.reviews.forEach((review) => {
    const card = make('article', 'review-item');
    const header = make('header');
    header.append(
      make('strong', 'rating-stars', `${'★'.repeat(review.stars)}${'☆'.repeat(5 - review.stars)}`),
      make('time', '', formatDate(review.created_at)),
    );
    card.append(header, make('p', '', review.comment || 'O cliente não deixou um comentário.'));
    card.append(make('small', '', `Corrida ${review.ride_code}`));
    list.append(card);
  });
};

const updateNotificationBadges = (count) => {
  const badge = document.getElementById('notification-badge');
  const shortcutBadge = document.getElementById('notification-shortcut-badge');
  [badge, shortcutBadge].forEach((node) => {
    if (!(node instanceof HTMLElement)) return;
    node.textContent = count > 99 ? '99+' : String(count);
    node.hidden = count <= 0;
  });
};

const loadNotifications = async () => {
  const result = await request('/api/driver/notifications?page_size=100');
  updateNotificationBadges(result.unread);
  const list = document.getElementById('notification-list');
  if (!(list instanceof HTMLElement)) return;
  list.replaceChildren();
  if (!result.notifications.length) {
    list.append(make('p', 'empty-note', 'Você ainda não recebeu notificações.'));
    return;
  }
  result.notifications.forEach((item) => {
    const card = make('article', `notification-item${item.read_at ? '' : ' is-unread'}`);
    const header = make('header');
    const title = make('strong', '', item.title);
    const time = make('time', '', formatDate(item.created_at));
    header.append(title, time);
    card.append(header, make('p', '', item.message));
    if (!item.read_at) {
      const mark = createActionButton('Marcar como lida', 'read-notification', item.id);
      mark.classList.remove('small-button');
      mark.classList.add('notification-read-button');
      card.append(mark);
    }
    list.append(card);
  });
};

document.getElementById('notification-list')?.addEventListener('click', async (event) => {
  const target = event.target instanceof Element ? event.target.closest('[data-action="read-notification"]') : null;
  if (!(target instanceof HTMLButtonElement)) return;
  try {
    await request(`/api/driver/notifications/${target.dataset.id}/read`, { method: 'PATCH' });
    await loadNotifications();
  } catch (error) {
    notify(error.message);
  }
});
document.getElementById('mark-all-read')?.addEventListener('click', async () => {
  try {
    await request('/api/driver/notifications/read-all', { method: 'PATCH' });
    await loadNotifications();
    notify('Notificações marcadas como lidas.', 'success');
  } catch (error) {
    notify(error.message);
  }
});
document.getElementById('notification-shortcut')?.addEventListener('click', () => switchView('notifications'));

const setAvatar = (avatar, name, photoUrl) => {
  if (!(avatar instanceof HTMLElement)) return;
  const initials = name.trim().split(/\s+/).slice(0, 2).map((part) => part[0] || '').join('').toUpperCase() || 'V';
  avatar.replaceChildren(document.createTextNode(initials));
  if (!photoUrl) return;
  const image = document.createElement('img');
  image.alt = '';
  image.src = `${photoUrl}?v=${Date.now()}`;
  image.addEventListener('error', () => {
    image.remove();
    avatar.textContent = initials;
  }, { once: true });
  avatar.replaceChildren(image);
};

const loadProfile = async () => {
  const profile = await request('/api/driver/profile');
  const values = {
    'profile-display-name': profile.name,
    'profile-display-email': profile.email,
    'profile-name': profile.name,
    'profile-email': profile.email,
    'profile-phone': profile.phone,
    'profile-motorcycle': profile.motorcycle,
    'profile-plate': profile.plate,
    'sidebar-name': profile.name,
    'sidebar-email': profile.email,
    'welcome-name': profile.name.split(/\s+/)[0],
  };
  Object.entries(values).forEach(([id, value]) => {
    const node = document.getElementById(id);
    if (node instanceof HTMLInputElement) node.value = value || '';
    else if (node) node.textContent = value || '';
  });
  setAvatar(document.getElementById('sidebar-avatar'), profile.name, profile.photo_url);
  setAvatar(document.getElementById('profile-avatar'), profile.name, profile.photo_url);
  const removePhoto = document.getElementById('remove-photo');
  if (removePhoto instanceof HTMLButtonElement) removePhoto.hidden = !profile.photo_url;
};

document.getElementById('profile-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const feedback = document.getElementById('profile-feedback');
  try {
    await request('/api/driver/profile', {
      method: 'PUT',
      body: JSON.stringify({
        phone: document.getElementById('profile-phone').value.trim(),
        motorcycle: document.getElementById('profile-motorcycle').value.trim(),
        plate: document.getElementById('profile-plate').value.trim(),
      }),
    });
    setFeedback(feedback, 'Perfil atualizado.', 'success');
    await loadProfile();
  } catch (error) {
    setFeedback(feedback, error.message);
  }
});

document.getElementById('photo-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const input = document.getElementById('profile-photo');
  const feedback = document.getElementById('photo-feedback');
  if (!(input instanceof HTMLInputElement) || !input.files?.[0]) {
    setFeedback(feedback, 'Escolha uma imagem antes de enviar.');
    return;
  }
  const photo = input.files[0];
  if (photo.size > 1_000_000) {
    setFeedback(feedback, 'A imagem deve ter no máximo 1 MB.');
    return;
  }
  try {
    const response = await fetch('/api/driver/profile/photo', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': photo.type },
      body: photo,
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || 'Não foi possível enviar a imagem.');
    setFeedback(feedback, 'Foto atualizada.', 'success');
    input.value = '';
    await loadProfile();
  } catch (error) {
    setFeedback(feedback, error.message);
  }
});

document.getElementById('remove-photo')?.addEventListener('click', async () => {
  try {
    await request('/api/driver/profile/photo', { method: 'DELETE' });
    await loadProfile();
    setFeedback(document.getElementById('photo-feedback'), 'Foto removida.', 'success');
  } catch (error) {
    setFeedback(document.getElementById('photo-feedback'), error.message);
  }
});

const signOut = async () => {
  try {
    await request('/api/logout', { method: 'POST' });
    window.location.replace('/login');
  } catch (error) {
    notify(error.message);
  }
};
document.querySelectorAll('[data-logout]').forEach((button) => {
  button.addEventListener('click', signOut);
});

document.getElementById('mobile-menu')?.addEventListener('click', () => {
  const open = appShell?.classList.toggle('mobile-nav-open');
  document.getElementById('mobile-menu')?.setAttribute('aria-expanded', String(Boolean(open)));
});
appShell?.addEventListener('click', (event) => {
  if (event.target === appShell && appShell.classList.contains('mobile-nav-open')) {
    appShell.classList.remove('mobile-nav-open');
    document.getElementById('mobile-menu')?.setAttribute('aria-expanded', 'false');
  }
});
document.getElementById('sidebar-collapse')?.addEventListener('click', (event) => {
  const button = event.currentTarget;
  const collapsed = appShell?.classList.toggle('sidebar-collapsed');
  button?.setAttribute('aria-pressed', String(Boolean(collapsed)));
  button?.setAttribute('aria-label', collapsed ? 'Expandir menu lateral' : 'Recolher menu lateral');
});

const initialize = async () => {
  try {
    const result = await request('/api/me');
    if (!result.user) {
      window.location.replace('/login?tipo=mototaxista');
      return;
    }
    if (result.user.accountType !== 'mototaxista') {
      window.location.replace('/inicio');
      return;
    }
    await Promise.all([loadProfile(), refreshAvailability(), loadNotifications()]);
    switchView('overview');
    window.setInterval(async () => {
      try {
        const status = await request('/api/driver/availability/heartbeat', { method: 'POST' });
        renderAvailability(status.online);
        if (status.online && document.querySelector('.view-panel.is-visible')?.dataset.view === 'rides') {
          await loadAvailableRides();
        }
        if (status.online && document.querySelector('.view-panel.is-visible')?.dataset.view === 'deliveries') {
          await loadAvailableDeliveries();
        }
      } catch (error) {
        notify(error.message);
      }
    }, 45_000);
    window.setInterval(() => {
      request('/api/driver/notifications?page_size=1')
        .then((data) => updateNotificationBadges(data.unread))
        .catch((error) => notify(error.message));
    }, 60_000);
  } catch (error) {
    notify(error.message);
  }
};

initialize();


