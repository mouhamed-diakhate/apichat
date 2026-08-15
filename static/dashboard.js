/* ============================================================
   Dashboard TexMiles — dashboard.js
   Widget chat connecté au parcours interactif complet
   (Langue → Menu principal → Agent IA)
   ============================================================ */

var page = 1;
var currentFilter = { intent: '', status: '', phone: '' };
var metricsPeriod = { startDate: '', endDate: '' };
var statsRequestSequence = 0;
var chartIntents = null;
var chartLangs = null;
var knownNotificationIds = {};
var notificationsPrimed = false;
var FAQ_API_BASE = '/api/v1/dashboard/faq';
var faqEntries = [];
var faqEditingId = null;
var faqSearchTimer = null;
var faqRequestSequence = 0;
var faqSaving = false;
var faqAccessDenied = false;

// Session unique par ouverture du widget
var demoSessionId = 'dashboard_' + Math.random().toString(36).substr(2, 9);
var demoStarted = false;

// ─── Auth helpers ─────────────────────────────────────────────────────────────

function getToken() {
  var match = document.cookie.match(/access_token=([^;]+)/);
  return match ? match[1] : null;
}

function setToken(token) {
  document.cookie = 'access_token=' + token + '; path=/';
}

function clearToken() {
  document.cookie = 'access_token=; Max-Age=0; path=/';
  knownNotificationIds = {};
  notificationsPrimed = false;
  metricsPeriod = { startDate: '', endDate: '' };
  statsRequestSequence += 1;
  faqEntries = [];
  faqEditingId = null;
  faqAccessDenied = false;
  faqRequestSequence += 1;
  var metricsStartDate = document.getElementById('metrics-start-date');
  var metricsEndDate = document.getElementById('metrics-end-date');
  if (metricsStartDate) metricsStartDate.value = '';
  if (metricsEndDate) {
    metricsEndDate.value = '';
    metricsEndDate.min = '';
  }
  setMetricsPeriodStatus();
  setMetricsPeriodFeedback('');
  setNotificationPanelOpen(false);
}

// ─── Utilitaires affichage ────────────────────────────────────────────────────

function maskEmail(email) {
  if (!email) return '—';
  var parts = email.split('@');
  return parts[0][0] + '***@' + parts[1][0] + '***';
}

function formatDate(iso) {
  var d = new Date(iso);
  return d.toLocaleDateString('fr-FR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
  });
}

// Le contenu des conversations provient de clients et ne doit jamais etre
// injecte directement dans le DOM. Le formatage Markdown reste volontairement
// limite au gras et aux retours a la ligne.
function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatRichText(value) {
  return escapeHtml(value)
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}

// ─── Fetch authentifié ────────────────────────────────────────────────────────

async function fetchJSONWithAuth(url, options) {
  var token = getToken();
  var requestOptions = options || {};
  var headers = { 'Content-Type': 'application/json' };
  if (requestOptions.headers) {
    Object.keys(requestOptions.headers).forEach(function (key) {
      headers[key] = requestOptions.headers[key];
    });
  }
  if (token) headers['Authorization'] = 'Bearer ' + token;
  requestOptions.headers = headers;
  var res = await fetch(url, requestOptions);
  if (!res.ok) {
    var payload = null;
    try {
      payload = await res.json();
    } catch (ignore) {
      // Certaines erreurs de proxy ne contiennent pas de JSON.
    }
    var detail = payload && (payload.detail || payload.message || payload.error);
    var error = new Error(typeof detail === 'string' ? detail : ('HTTP ' + res.status));
    error.status = res.status;
    throw error;
  }
  if (res.status === 204) return null;
  return res.json();
}

// ─── Panneau login/dashboard ─────────────────────────────────────────────────

function setLoginState() {
  var logged = !!getToken();
  var loginPanel = document.getElementById('login-panel');
  var dashboardApp = document.getElementById('dashboard-app');
  if (loginPanel && dashboardApp) {
    loginPanel.style.display = logged ? 'none' : 'block';
    dashboardApp.style.display = logged ? 'block' : 'none';
  }
  if (logged) {
    faqAccessDenied = false;
    loadStats();
    loadConversations();
    loadNotifications();
    loadFaqs();
  } else {
    setNotificationPanelOpen(false);
  }
}

// ─── KPIs et période ──────────────────────────────────────────────────────────

function isIsoDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value || '');
}

function formatDateOnly(value) {
  if (!isIsoDate(value)) return '—';
  var parts = value.split('-');
  return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
    .toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function setMetricsPeriodStatus() {
  var status = document.getElementById('metrics-period-status');
  if (!status) return;

  if (metricsPeriod.startDate && metricsPeriod.endDate) {
    status.textContent = 'Période : du ' + formatDateOnly(metricsPeriod.startDate) + ' au ' + formatDateOnly(metricsPeriod.endDate);
  } else if (metricsPeriod.startDate) {
    status.textContent = 'Période : depuis le ' + formatDateOnly(metricsPeriod.startDate);
  } else if (metricsPeriod.endDate) {
    status.textContent = 'Période : jusqu’au ' + formatDateOnly(metricsPeriod.endDate);
  } else {
    status.textContent = 'Période : toutes les données disponibles';
  }
}

function setMetricsPeriodFeedback(message) {
  var feedback = document.getElementById('metrics-period-feedback');
  if (!feedback) return;
  feedback.textContent = message || '';
  feedback.hidden = !message;
  feedback.classList.toggle('error', !!message);
}

function numberFromMetric(value) {
  if (value === null || value === undefined || value === '') return null;
  var parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatMetricCount(value) {
  var count = numberFromMetric(value);
  return count === null ? '—' : Math.round(count).toLocaleString('fr-FR');
}

function percentageFromRate(value) {
  var rate = numberFromMetric(value);
  if (rate === null) return null;
  var percentage = rate <= 1 ? rate * 100 : rate;
  return Math.max(0, Math.min(100, percentage));
}

function formatRate(value) {
  var percentage = percentageFromRate(value);
  return percentage === null ? '—' : percentage.toFixed(1) + ' %';
}

function formatHumanResponseDelay(value) {
  var minutes = numberFromMetric(value);
  if (minutes === null || minutes < 0) return '—';
  var rounded = Math.round(minutes);
  if (rounded < 60) return rounded + ' min';
  var hours = Math.floor(rounded / 60);
  var remainingMinutes = rounded % 60;
  return hours + ' h' + (remainingMinutes ? ' ' + remainingMinutes + ' min' : '');
}

function setKpiValue(id, value) {
  var element = document.getElementById(id);
  if (element) element.textContent = value;
}

function getIntentName(intent) {
  return INTENT_INFO[intent] || 'Général';
}

function updateKPIs(data) {
  setKpiValue('kpi-messages', formatMetricCount(data.total_messages_recus));
  setKpiValue('kpi-conversations', formatMetricCount(data.total_conversations));

  var autoRes = data.autonomous_resolution_rate !== undefined
    ? data.autonomous_resolution_rate
    : (1.0 - (data.escalation_rate || 0));
  setKpiValue('kpi-autonome', formatRate(autoRes));
  setKpiValue('kpi-escalade', formatRate(data.escalation_rate));
  setKpiValue('kpi-tickets', formatMetricCount(data.tickets_created));
  setKpiValue('kpi-human-response', formatHumanResponseDelay(data.average_human_response_minutes));

  var entries = Object.entries(data.languages || {});
  var top = entries.sort(function (a, b) { return b[1] - a[1]; })[0];
  setKpiValue('kpi-langue', top ? top[0].toUpperCase() : '—');
  var lastUpdate = document.getElementById('last-update');
  if (lastUpdate) lastUpdate.textContent = new Date().toLocaleTimeString('fr-FR');
}

function renderIntentResolution(data) {
  var container = document.getElementById('intent-resolution-list');
  if (!container) return;
  container.innerHTML = '';

  var rates = data.resolution_rate_by_intent || {};
  var entries = Object.keys(rates).map(function (intent) {
    return {
      intent: intent,
      rate: percentageFromRate(rates[intent])
    };
  }).filter(function (entry) {
    return entry.rate !== null;
  }).sort(function (left, right) {
    return right.rate - left.rate;
  });

  if (entries.length === 0) {
    var empty = document.createElement('p');
    empty.className = 'intent-resolution-empty';
    empty.textContent = 'Aucune donnée de résolution disponible pour cette période.';
    container.appendChild(empty);
    return;
  }

  entries.forEach(function (entry) {
    var row = document.createElement('div');
    row.className = 'intent-resolution-row';
    row.setAttribute('role', 'listitem');

    var label = document.createElement('strong');
    label.className = 'intent-resolution-label';
    label.textContent = getIntentName(entry.intent);

    var value = document.createElement('span');
    value.className = 'intent-resolution-value';
    value.textContent = entry.rate.toFixed(1) + ' %';

    var track = document.createElement('div');
    track.className = 'intent-resolution-track';
    track.setAttribute('role', 'progressbar');
    track.setAttribute('aria-label', 'Taux de résolution ' + getIntentName(entry.intent));
    track.setAttribute('aria-valuemin', '0');
    track.setAttribute('aria-valuemax', '100');
    track.setAttribute('aria-valuenow', entry.rate.toFixed(1));

    var bar = document.createElement('span');
    bar.className = 'intent-resolution-bar';
    bar.style.width = entry.rate + '%';
    track.appendChild(bar);

    row.appendChild(label);
    row.appendChild(value);
    row.appendChild(track);
    container.appendChild(row);
  });
}


// ─── Graphiques ───────────────────────────────────────────────────────────────

function renderCharts(data) {
  var intentsCtx = document.getElementById('chart-intents').getContext('2d');
  var intents = data.top_intents || {};
  var labels = Object.keys(intents);
  var values = Object.values(intents);
  var colors = ['#fdb813', '#1a1a1a', '#4d4d4d', '#e5a500', '#cccccc', '#2e7d32'];

  if (chartIntents) chartIntents.destroy();
  chartIntents = new Chart(intentsCtx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Messages',
        data: values,
        backgroundColor: colors.slice(0, labels.length),
        borderRadius: 6,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, ticks: { stepSize: 1 } },
        x: { grid: { display: false } }
      }
    }
  });

  var langsCtx = document.getElementById('chart-langs').getContext('2d');
  var langs = data.languages || {};
  var langLabels = Object.keys(langs);
  var langValues = Object.values(langs);

  if (chartLangs) chartLangs.destroy();
  chartLangs = new Chart(langsCtx, {
    type: 'doughnut',
    data: {
      labels: langLabels,
      datasets: [{
        data: langValues,
        backgroundColor: ['#fdb813', '#1a1a1a', '#4d4d4d'],
        borderWidth: 0,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { font: { size: 12 } } }
      }
    }
  });
}

// ─── Tableau conversations ────────────────────────────────────────────────────

// ─── Icônes SVG (style Lucide, prennent la couleur du texte) ─────────────────

function svgIcon(inner) {
  return '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + inner + '</svg>';
}

var ICONS = {
  tracking: svgIcon('<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>'),
  quotation: svgIcon('<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect width="8" height="4" x="8" y="2" rx="1"/><path d="M8 11h8"/><path d="M8 15h5"/>'),
  operation: svgIcon('<path d="M14 18V6a1 1 0 0 0-1-1H2a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h1"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.62l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>'),
  claim: svgIcon('<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>'),
  faq: svgIcon('<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>'),
  human: svgIcon('<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>'),
  general: svgIcon('<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>'),
  check: svgIcon('<path d="M20 6 9 17l-5-5"/>'),
  alert: svgIcon('<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>'),
  tool: svgIcon('<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76Z"/>')
};

// ─── Libellés (langue en pastille de code, intention avec icône) ─────────────

var LANG_INFO = { wo: ['WO', 'Wolof'], en: ['EN', 'English'], ar: ['AR', 'العربية'], fr: ['FR', 'Français'] };

function getLanguageFlag(lang) {
  var v = LANG_INFO[lang] || LANG_INFO.fr;
  return '<span class="lang-code">' + v[0] + '</span>' + v[1];
}

var INTENT_INFO = {
  tracking: 'Suivi', quotation: 'Cotation', operation: 'Opération',
  claim: 'Réclamation', faq: 'FAQ', human: 'Escalade'
};

function getIntentLabel(intent) {
  var key = INTENT_INFO[intent] ? intent : 'general';
  var label = INTENT_INFO[intent] || 'Général';
  return '<span class="intent-badge ' + key + '">' + (ICONS[key] || ICONS.general) + '<span>' + label + '</span></span>';
}

// ─── Drawer Detail Conversation ──────────────────────────────────────────────

function getConversationStatus(item) {
  var status = item.status || (item.escalade ? 'escalade' : 'repondu');
  if (status === 'en_attente') {
    return {
      className: 'status-pending',
      inlineClass: 'pending',
      icon: ICONS.alert,
      text: 'Nouveau - en attente'
    };
  }
  if (status === 'escalade') {
    return {
      className: 'status-escalated',
      inlineClass: 'danger',
      icon: ICONS.alert,
      text: item.raison_escalade || 'Escalade humaine'
    };
  }
  if (status === 'traite') {
    return {
      className: 'status-treated',
      inlineClass: 'success',
      icon: ICONS.check,
      text: 'Traité par l\'équipe'
    };
  }
  return {
    className: 'status-resolved',
    inlineClass: 'success',
    icon: ICONS.check,
    text: 'Répondu par l\'IA'
  };
}

function getConversationStatusHtml(item) {
  var state = getConversationStatus(item);
  return '<span class="status-inline ' + state.inlineClass + '">' + state.icon + ' ' + state.text + '</span>';
}

function setActionDisabled(button, disabled) {
  if (!button) return;
  button.disabled = disabled;
  button.setAttribute('aria-disabled', disabled ? 'true' : 'false');
}

function configureResolveButton(data) {
  var button = document.getElementById('btn-resolve-claim');
  var label = document.getElementById('btn-resolve-label');
  if (!button) return;

  button.dataset.conversationId = data.id || '';
  var canResolve = Boolean(data.escalade) && data.status !== 'traite';
  button.disabled = !canResolve;
  button.setAttribute('aria-disabled', canResolve ? 'false' : 'true');

  if (canResolve) {
    button.title = 'Marquer cette escalade comme traitée';
    if (label) label.textContent = 'Marquer comme traité';
  } else if (data.status === 'traite') {
    button.title = 'Cette escalade a déjà été traitée';
    if (label) label.textContent = 'Déjà traité';
  } else {
    button.title = 'Aucune escalade à traiter dans cette conversation';
    if (label) label.textContent = 'Aucune escalade';
  }
}

async function openDrawer(msgId) {
  var drawer = document.getElementById('conv-drawer');
  var overlay = document.getElementById('drawer-overlay');
  var transcript = document.getElementById('drawer-transcript');
  if (!drawer || !overlay || !transcript) return;
  var resolveButton = document.getElementById('btn-resolve-claim');
  var resolveLabel = document.getElementById('btn-resolve-label');
  if (resolveButton) {
    setActionDisabled(resolveButton, true);
    resolveButton.dataset.conversationId = '';
    if (resolveLabel) resolveLabel.textContent = 'Chargement…';
  }
  try {
    transcript.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-muted)">Chargement de la discussion...</div>';
    drawer.classList.add('active');
    overlay.classList.add('active');

    var data = await fetchJSONWithAuth('/api/v1/dashboard/conversations/' + msgId);
    if (data.error) {
      transcript.innerHTML = '<div style="color:var(--danger);padding:1rem;">Erreur: ' + escapeHtml(data.error) + '</div>';
      return;
    }

    // Infos en-tête client
    var clientName = data.client ? (data.client.display || data.client.phone_number || data.client.full_name) : 'Client Invité';
    var clientSub = data.client ? (data.client.phone_number || data.client.email || 'Visiteur') : 'Visiteur';
    document.getElementById('drawer-client-name').textContent = clientName;
    document.getElementById('drawer-client-email').textContent = clientSub;
    document.getElementById('drawer-intent').innerHTML = getIntentLabel(data.intent);
    document.getElementById('drawer-lang').innerHTML = '<span class="lang-flag">' + getLanguageFlag(data.language) + '</span>';

    // Le contact doit viser exclusivement le numero de la conversation ouverte.
    // Aucun numero de demonstration ne doit etre utilise comme solution de repli.
    var btnWhatsapp = document.getElementById('btn-contact-client');
    var btnWhatsappLabel = document.getElementById('btn-contact-client-label');
    if (btnWhatsapp) {
      var rawPhone = (data.client && data.client.raw_phone ? String(data.client.raw_phone) : '').replace(/\D/g, '');
      if (rawPhone) {
        var displayPhone = data.client.phone_number || ('+' + rawPhone);
        btnWhatsapp.disabled = false;
        btnWhatsapp.removeAttribute('aria-disabled');
        btnWhatsapp.title = 'Contacter ' + displayPhone + ' sur WhatsApp';
        if (btnWhatsappLabel) btnWhatsappLabel.textContent = 'Contacter ' + displayPhone;
        btnWhatsapp.onclick = function () {
          var greeting = 'Bonjour, ici le service client TexMiles. Comment pouvons-nous vous aider ?';
          window.open(
            'https://wa.me/' + rawPhone + '?text=' + encodeURIComponent(greeting),
            '_blank',
            'noopener'
          );
        };
      } else {
        btnWhatsapp.disabled = true;
        btnWhatsapp.setAttribute('aria-disabled', 'true');
        btnWhatsapp.title = 'Numero WhatsApp indisponible pour ce client';
        if (btnWhatsappLabel) btnWhatsappLabel.textContent = 'Numero WhatsApp indisponible';
        btnWhatsapp.onclick = null;
      }
    }

    document.getElementById('drawer-status').innerHTML = getConversationStatusHtml(data);
    configureResolveButton(data);

    document.getElementById('drawer-ticket').textContent = data.ticket_id || '—';

    // Rendu de la transcription
    transcript.innerHTML = '';
    if (!data.messages || data.messages.length === 0) {
      transcript.innerHTML = '<div style="text-align:center;color:var(--text-muted)">Aucun message enregistré.</div>';
      return;
    }

    data.messages.forEach(function (m) {
      var div = document.createElement('div');
      div.className = 't-msg ' + (m.role === 'user' ? 'user' : 'assistant');

      var contentFormatted = formatRichText(m.content);
      var timeStr = formatDate(m.created_at);

      var toolsBadge = m.outils_utilises ? '<div class="t-tool">' + ICONS.tool + ' Outil: ' + escapeHtml(m.outils_utilises) + '</div>' : '';

      div.innerHTML = contentFormatted + toolsBadge + '<span class="t-msg-time">' + timeStr + '</span>';
      transcript.appendChild(div);
    });

    transcript.scrollTop = transcript.scrollHeight;
  } catch (err) {
    console.error('Erreur ouverture drawer:', err);
    transcript.innerHTML = '<div style="color:var(--danger);padding:1rem;">Erreur de chargement: ' + escapeHtml(err.message) + '</div>';
  }
}

function closeDrawer() {
  var drawer = document.getElementById('conv-drawer');
  var overlay = document.getElementById('drawer-overlay');
  if (drawer) drawer.classList.remove('active');
  if (overlay) overlay.classList.remove('active');
  var resolveButton = document.getElementById('btn-resolve-claim');
  if (resolveButton) resolveButton.dataset.conversationId = '';
}

// ─── Tableau conversations ────────────────────────────────────────────────────

async function loadConversations() {
  var params = new URLSearchParams({ page: page, page_size: 20 });
  if (currentFilter.intent) params.set('intent', currentFilter.intent);
  if (currentFilter.status) params.set('status', currentFilter.status);
  if (currentFilter.phone) params.set('phone', currentFilter.phone);

  try {
    var data = await fetchJSONWithAuth('/api/v1/dashboard/conversations?' + params.toString());
    var lastUpdate = document.getElementById('last-update');
    if (lastUpdate) lastUpdate.textContent = new Date().toLocaleTimeString('fr-FR');
    var tbody = document.getElementById('conv-body');
    tbody.innerHTML = '';

    if (data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">Aucune conversation trouvée</td></tr>';
      return;
    }

    data.items.forEach(function (item) {
      var tr = document.createElement('tr');
      tr.className = 'clickable-row';
      var statusClass = item.escalade ? 'status-escalated' : 'status-resolved';
      var statusText = item.escalade ? (item.raison_escalade || 'Escaladé') : 'Résolu';
      var ticket = item.ticket_id ? '<span class="ticket-link">' + item.ticket_id + '</span>' : '—';
      var conversationStatus = getConversationStatus(item);
      if (item.ticket_id) {
        ticket = '<span class="ticket-link">' + escapeHtml(item.ticket_id) + '</span>';
      }
      statusClass = conversationStatus.className;
      statusText = conversationStatus.text;
      var clientLabel = item.client_display || item.user_phone || item.user_name || item.user_email;
      var safeClientLabel = escapeHtml(clientLabel);
      var safePreview = escapeHtml(item.message_preview || '');

      tr.innerHTML =
        '<td>' + formatDate(item.created_at) + '</td>' +
        '<td><strong style="color:#2563eb;font-size:13px;">' + safeClientLabel + '</strong></td>' +
        '<td>' + getIntentLabel(item.intent) + '</td>' +
        '<td><span class="lang-flag">' + getLanguageFlag(item.language) + '</span></td>' +
        '<td class="' + statusClass + '">' + statusText + '</td>' +
        '<td>' + ticket + '</td>' +
        '<td class="preview-text" title="' + safePreview + '">' + safePreview + '</td>';

      tr.addEventListener('click', function () {
        openDrawer(item.id);
      });

      tbody.appendChild(tr);
    });

    var totalPages = Math.ceil(data.total / data.page_size);
    var nav = document.getElementById('pagination');
    nav.innerHTML = '';
    for (var i = 1; i <= totalPages; i++) {
      (function (pageNum) {
        var btn = document.createElement('button');
        btn.textContent = pageNum;
        btn.className = pageNum === page ? 'active' : '';
        btn.addEventListener('click', function () { page = pageNum; loadConversations(); });
        nav.appendChild(btn);
      })(i);
    }
  } catch (err) {
    document.getElementById('conv-body').innerHTML =
      '<tr><td colspan="7" style="text-align:center;color:var(--danger)">Erreur: ' + escapeHtml(err.message) + '</td></tr>';
  }
}

async function loadStats() {
  if (!getToken()) return;
  var requestSequence = ++statsRequestSequence;
  var params = new URLSearchParams();
  if (metricsPeriod.startDate) params.set('start_date', metricsPeriod.startDate);
  if (metricsPeriod.endDate) params.set('end_date', metricsPeriod.endDate);
  var query = params.toString();

  try {
    var data = await fetchJSONWithAuth('/api/v1/dashboard/stats' + (query ? '?' + query : ''));
    if (requestSequence !== statsRequestSequence) return;
    updateKPIs(data);
    renderCharts(data);
    renderIntentResolution(data);
    setMetricsPeriodFeedback('');
  } catch (err) {
    if (requestSequence !== statsRequestSequence) return;
    console.error('Stats error:', err);
    setMetricsPeriodFeedback('Impossible de charger les indicateurs pour cette période. Réessayez.');
  }
}

function dashboardExportUrl() {
  var params = new URLSearchParams();
  if (metricsPeriod.startDate) params.set('start_date', metricsPeriod.startDate);
  if (metricsPeriod.endDate) params.set('end_date', metricsPeriod.endDate);
  if (currentFilter.intent) params.set('intent', currentFilter.intent);
  if (currentFilter.status) params.set('status', currentFilter.status);
  var query = params.toString();
  return '/api/v1/dashboard/exports/tickets-escalades.csv' + (query ? '?' + query : '');
}

async function exportTicketsAndEscalationsCsv(button) {
  if (!getToken() || !button || button.disabled) return;
  var previousLabel = button.textContent;
  button.disabled = true;
  button.textContent = 'Préparation…';
  try {
    var response = await fetch(dashboardExportUrl(), {
      headers: { 'Authorization': 'Bearer ' + getToken() }
    });
    if (!response.ok) {
      var errorPayload = null;
      try { errorPayload = await response.json(); } catch (ignore) { /* no-op */ }
      throw new Error((errorPayload && errorPayload.detail) || ('HTTP ' + response.status));
    }
    var blob = await response.blob();
    var url = window.URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = 'texmiles_tickets_escalades.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () { window.URL.revokeObjectURL(url); }, 0);
    setMetricsPeriodFeedback('');
  } catch (error) {
    console.error('Erreur export CSV:', error);
    setMetricsPeriodFeedback('Impossible de générer l’export CSV. Réessayez.');
  } finally {
    button.disabled = false;
    button.textContent = previousLabel;
  }
}

// Notifications d'escalade
function setNotificationPanelOpen(isOpen) {
  var panel = document.getElementById('notification-panel');
  var bell = document.getElementById('notification-bell');
  if (!panel || !bell) return;
  panel.classList.toggle('open', isOpen);
  bell.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
}

function notificationMeta(notification) {
  var parts = [];
  if (notification.client_display) parts.push(notification.client_display);
  if (notification.ticket_id) parts.push(notification.ticket_id);
  if (notification.created_at) parts.push(formatDate(notification.created_at));
  return parts.join(' · ');
}

function openNotification(notification) {
  setNotificationPanelOpen(false);
  if (notification.conversation_id) openDrawer(notification.conversation_id);

  fetchJSONWithAuth(
    '/api/v1/dashboard/notifications/' + notification.id + '/read',
    { method: 'POST' }
  ).catch(function (err) {
    console.error('Erreur de lecture de notification:', err);
  }).finally(function () {
    loadNotifications();
  });
}

function renderNotifications(data) {
  var badge = document.getElementById('notification-badge');
  var count = Number(data.unread_count || 0);
  if (badge) {
    badge.hidden = count === 0;
    badge.textContent = count > 99 ? '99+' : String(count);
  }

  var panelCount = document.getElementById('notification-panel-count');
  if (panelCount) panelCount.textContent = count ? String(count) : 'Aucune';

  var list = document.getElementById('notification-list');
  if (!list) return;
  list.innerHTML = '';
  var items = data.items || [];
  if (items.length === 0) {
    var empty = document.createElement('p');
    empty.className = 'notification-empty';
    empty.textContent = 'Aucune escalade non lue.';
    list.appendChild(empty);
    return;
  }

  items.forEach(function (notification) {
    var item = document.createElement('button');
    item.type = 'button';
    item.className = 'notification-item';

    var title = document.createElement('strong');
    title.textContent = notification.title || 'Nouvelle escalade client';
    var body = document.createElement('p');
    body.textContent = notification.body || 'Une intervention humaine est requise.';
    var meta = document.createElement('small');
    meta.textContent = notificationMeta(notification);
    item.appendChild(title);
    item.appendChild(body);
    item.appendChild(meta);
    item.addEventListener('click', function () { openNotification(notification); });
    list.appendChild(item);
  });
}

function showNotificationToast(notification) {
  var container = document.getElementById('notification-toasts');
  if (!container) return;

  var toast = document.createElement('article');
  toast.className = 'notification-toast';
  var text = document.createElement('div');
  var title = document.createElement('strong');
  title.textContent = notification.title || 'Nouvelle escalade client';
  var body = document.createElement('p');
  body.textContent = notification.body || 'Une intervention humaine est requise.';
  text.appendChild(title);
  text.appendChild(body);

  var open = document.createElement('button');
  open.type = 'button';
  open.className = 'notification-toast-open';
  open.textContent = 'Ouvrir';
  open.addEventListener('click', function () {
    toast.remove();
    openNotification(notification);
  });
  toast.appendChild(text);
  toast.appendChild(open);
  container.appendChild(toast);
  window.setTimeout(function () { toast.remove(); }, 9000);
}

async function loadNotifications() {
  if (!getToken()) return;
  try {
    var data = await fetchJSONWithAuth('/api/v1/dashboard/notifications?unread_only=true&limit=20');
    var items = data.items || [];
    items.forEach(function (notification) {
      if (notificationsPrimed && !knownNotificationIds[notification.id]) {
        showNotificationToast(notification);
      }
      knownNotificationIds[notification.id] = true;
    });
    notificationsPrimed = true;
    renderNotifications(data);
  } catch (err) {
    console.error('Notifications error:', err);
  }
}

// ─── Widget Chat Interactif (Langue → Menu → Agent IA) ───────────────────────

// ─── Gestion de la FAQ (sans édition directe de JSON) ────────────────────────

function faqItemsFromResponse(data) {
  if (Array.isArray(data)) return data;
  if (!data || typeof data !== 'object') return [];
  var candidates = [data.items, data.faqs, data.entrees, data.results, data.data];
  for (var i = 0; i < candidates.length; i += 1) {
    if (Array.isArray(candidates[i])) return candidates[i];
  }
  return [];
}

function normaliseFaqKeywords(value) {
  if (Array.isArray(value)) {
    return value.map(function (keyword) { return String(keyword || '').trim(); }).filter(Boolean);
  }
  if (typeof value === 'string') {
    return value.split(/[\n,;]/).map(function (keyword) { return keyword.trim(); }).filter(Boolean);
  }
  return [];
}

function normaliseFaqEntry(entry) {
  entry = entry || {};
  return {
    id: entry.id === undefined || entry.id === null ? '' : String(entry.id),
    question: String(entry.question || entry.title || ''),
    reponse: String(entry.reponse !== undefined ? entry.reponse : (entry.answer !== undefined ? entry.answer : (entry.response || ''))),
    mots_cles: normaliseFaqKeywords(entry.mots_cles !== undefined ? entry.mots_cles : entry.keywords),
    raw: entry
  };
}

function faqEntryFromResponse(data) {
  if (!data || typeof data !== 'object') return null;
  return normaliseFaqEntry(data.item || data.faq || data.entry || data);
}

function faqErrorMessage(error, action) {
  if (error && error.status === 403) {
    return 'Accès refusé : la gestion de la FAQ est réservée aux agents administrateurs.';
  }
  if (error && error.status === 401) {
    return 'Votre session a expiré. Connectez-vous à nouveau pour gérer la FAQ.';
  }
  var detail = error && error.message ? error.message : 'Erreur inconnue';
  return (action || 'Opération impossible') + ' : ' + detail;
}

function showFaqFeedback(message, kind) {
  var feedback = document.getElementById('faq-feedback');
  if (!feedback) return;
  feedback.className = 'faq-feedback ' + (kind || 'info');
  feedback.textContent = message;
  feedback.hidden = false;
}

function clearFaqFeedback() {
  var feedback = document.getElementById('faq-feedback');
  if (!feedback) return;
  feedback.textContent = '';
  feedback.className = 'faq-feedback';
  feedback.hidden = true;
}

function updateFaqEditorControls() {
  var form = document.getElementById('faq-form');
  var save = document.getElementById('faq-save-btn');
  var cancel = document.getElementById('faq-cancel-btn');
  var remove = document.getElementById('faq-delete-btn');
  var newButton = document.getElementById('faq-new-btn');
  var reload = document.getElementById('faq-reload-btn');
  var blocked = faqSaving || faqAccessDenied;

  if (form) {
    form.querySelectorAll('input, textarea').forEach(function (control) {
      control.disabled = blocked;
    });
  }
  if (save) save.disabled = blocked;
  if (cancel) {
    cancel.hidden = !faqEditingId;
    cancel.disabled = blocked;
  }
  if (remove) {
    remove.disabled = blocked || !faqEditingId;
    remove.setAttribute('aria-disabled', remove.disabled ? 'true' : 'false');
  }
  if (newButton) newButton.disabled = blocked;
  if (reload) reload.disabled = blocked;
}

function setFaqListLoading(isLoading) {
  var list = document.getElementById('faq-list');
  var reload = document.getElementById('faq-reload-btn');
  if (list) list.setAttribute('aria-busy', isLoading ? 'true' : 'false');
  if (reload) reload.disabled = isLoading || faqSaving || faqAccessDenied;
}

function resetFaqForm(options) {
  options = options || {};
  var form = document.getElementById('faq-form');
  var title = document.getElementById('faq-form-title');
  var id = document.getElementById('faq-entry-id');
  var question = document.getElementById('faq-question');
  faqEditingId = null;
  if (form) form.reset();
  if (id) id.value = '';
  if (title) title.textContent = 'Ajouter une FAQ';
  updateFaqEditorControls();
  renderFaqList();
  if (options.focus && question && !question.disabled) question.focus();
}

function selectFaqEntry(entry) {
  if (!entry || !entry.id) return;
  faqEditingId = String(entry.id);
  var id = document.getElementById('faq-entry-id');
  var question = document.getElementById('faq-question');
  var answer = document.getElementById('faq-answer');
  var keywords = document.getElementById('faq-keywords');
  var title = document.getElementById('faq-form-title');
  if (id) id.value = faqEditingId;
  if (question) question.value = entry.question;
  if (answer) answer.value = entry.reponse;
  if (keywords) keywords.value = entry.mots_cles.join(', ');
  if (title) title.textContent = 'Modifier la FAQ';
  clearFaqFeedback();
  updateFaqEditorControls();
  renderFaqList();
  if (question && !question.disabled) question.focus();
}

function renderFaqList() {
  var list = document.getElementById('faq-list');
  var status = document.getElementById('faq-list-status');
  if (!list || !status) return;

  list.innerHTML = '';
  if (faqAccessDenied) {
    status.textContent = 'Accès réservé aux agents administrateurs.';
    return;
  }
  if (faqEntries.length === 0) {
    status.textContent = 'Aucune FAQ trouvée.';
    var empty = document.createElement('li');
    empty.className = 'faq-empty';
    empty.textContent = 'Ajoutez votre première réponse FAQ à l’aide du formulaire.';
    list.appendChild(empty);
    return;
  }

  status.textContent = faqEntries.length + (faqEntries.length > 1 ? ' FAQ trouvées.' : ' FAQ trouvée.');
  faqEntries.forEach(function (entry) {
    var row = document.createElement('li');
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'faq-list-item';
    button.disabled = !entry.id || faqSaving;
    button.setAttribute('aria-current', entry.id && entry.id === faqEditingId ? 'true' : 'false');
    if (!entry.id) button.title = 'Cette FAQ ne peut pas être modifiée car son identifiant est absent.';

    var question = document.createElement('span');
    question.className = 'faq-list-question';
    question.textContent = entry.question || 'Question sans titre';
    button.appendChild(question);

    var keywords = document.createElement('span');
    keywords.className = 'faq-list-keywords';
    keywords.textContent = entry.mots_cles.length ? entry.mots_cles.join(', ') : 'Aucun mot-clé';
    button.appendChild(keywords);

    button.addEventListener('click', function () { selectFaqEntry(entry); });
    row.appendChild(button);
    list.appendChild(row);
  });
}

function faqListUrl() {
  var search = document.getElementById('faq-search');
  var params = new URLSearchParams();
  var query = search ? search.value.trim() : '';
  if (query) params.set('q', query);
  params.set('page', '1');
  params.set('page_size', '100');
  return FAQ_API_BASE + '?' + params.toString();
}

async function loadFaqs() {
  if (!getToken() || faqAccessDenied) return;
  var requestId = ++faqRequestSequence;
  var status = document.getElementById('faq-list-status');
  setFaqListLoading(true);
  if (status) status.textContent = 'Chargement des FAQ…';
  try {
    var data = await fetchJSONWithAuth(faqListUrl());
    if (requestId !== faqRequestSequence) return;
    faqEntries = faqItemsFromResponse(data).map(normaliseFaqEntry);
    renderFaqList();
  } catch (error) {
    if (requestId !== faqRequestSequence) return;
    console.error('Erreur de chargement des FAQ:', error);
    if (error && error.status === 403) {
      faqAccessDenied = true;
      faqEntries = [];
      renderFaqList();
    } else if (status) {
      status.textContent = 'Impossible de charger les FAQ.';
    }
    showFaqFeedback(faqErrorMessage(error, 'Impossible de charger les FAQ'), 'error');
  } finally {
    if (requestId === faqRequestSequence) {
      setFaqListLoading(false);
      updateFaqEditorControls();
    }
  }
}

function faqPayloadFromForm() {
  var question = document.getElementById('faq-question');
  var answer = document.getElementById('faq-answer');
  var keywords = document.getElementById('faq-keywords');
  return {
    question: question ? question.value.trim() : '',
    reponse: answer ? answer.value.trim() : '',
    mots_cles: normaliseFaqKeywords(keywords ? keywords.value : '')
  };
}

async function saveFaq(event) {
  event.preventDefault();
  if (faqSaving || faqAccessDenied) return;
  var payload = faqPayloadFromForm();
  var questionInput = document.getElementById('faq-question');
  var answerInput = document.getElementById('faq-answer');
  if (!payload.question) {
    showFaqFeedback('La question est obligatoire.', 'error');
    if (questionInput) questionInput.focus();
    return;
  }
  if (!payload.reponse) {
    showFaqFeedback('La réponse est obligatoire.', 'error');
    if (answerInput) answerInput.focus();
    return;
  }

  var previousId = faqEditingId;
  var editing = Boolean(previousId);
  faqSaving = true;
  updateFaqEditorControls();
  try {
    var url = editing ? FAQ_API_BASE + '/' + encodeURIComponent(previousId) : FAQ_API_BASE;
    var result = await fetchJSONWithAuth(url, {
      method: editing ? 'PUT' : 'POST',
      body: JSON.stringify(payload)
    });
    var saved = faqEntryFromResponse(result);
    var savedId = saved && saved.id ? saved.id : previousId;
    showFaqFeedback(editing ? 'FAQ mise à jour avec succès.' : 'FAQ ajoutée avec succès.', 'success');
    if (!editing) resetFaqForm();
    await loadFaqs();
    if (savedId) {
      var refreshed = faqEntries.find(function (entry) { return entry.id === String(savedId); });
      if (refreshed) selectFaqEntry(refreshed);
    }
  } catch (error) {
    console.error('Erreur d’enregistrement de la FAQ:', error);
    if (error && error.status === 403) faqAccessDenied = true;
    showFaqFeedback(faqErrorMessage(error, 'Impossible d’enregistrer la FAQ'), 'error');
    if (faqAccessDenied) renderFaqList();
  } finally {
    faqSaving = false;
    updateFaqEditorControls();
  }
}

async function deleteFaq() {
  if (!faqEditingId || faqSaving || faqAccessDenied) return;
  var entry = faqEntries.find(function (item) { return item.id === faqEditingId; });
  var description = entry && entry.question ? '« ' + entry.question + ' »' : 'cette FAQ';
  if (!window.confirm('Supprimer définitivement ' + description + ' ? Cette action est irréversible.')) return;

  var id = faqEditingId;
  faqSaving = true;
  updateFaqEditorControls();
  try {
    await fetchJSONWithAuth(FAQ_API_BASE + '/' + encodeURIComponent(id), { method: 'DELETE' });
    resetFaqForm();
    await loadFaqs();
    showFaqFeedback('FAQ supprimée.', 'success');
  } catch (error) {
    console.error('Erreur de suppression de la FAQ:', error);
    if (error && error.status === 403) faqAccessDenied = true;
    showFaqFeedback(faqErrorMessage(error, 'Impossible de supprimer la FAQ'), 'error');
    if (faqAccessDenied) renderFaqList();
  } finally {
    faqSaving = false;
    updateFaqEditorControls();
  }
}

function initFaqManager() {
  var form = document.getElementById('faq-form');
  var search = document.getElementById('faq-search');
  var newButton = document.getElementById('faq-new-btn');
  var reload = document.getElementById('faq-reload-btn');
  var cancel = document.getElementById('faq-cancel-btn');
  var remove = document.getElementById('faq-delete-btn');
  if (!form) return;

  form.addEventListener('submit', saveFaq);
  if (newButton) {
    newButton.addEventListener('click', function () {
      clearFaqFeedback();
      resetFaqForm({ focus: true });
    });
  }
  if (reload) {
    reload.addEventListener('click', function () {
      clearFaqFeedback();
      loadFaqs();
    });
  }
  if (cancel) {
    cancel.addEventListener('click', function () {
      clearFaqFeedback();
      resetFaqForm({ focus: true });
    });
  }
  if (remove) remove.addEventListener('click', deleteFaq);
  if (search) {
    search.addEventListener('input', function () {
      window.clearTimeout(faqSearchTimer);
      faqSearchTimer = window.setTimeout(loadFaqs, 260);
    });
  }
  updateFaqEditorControls();
}

function createDemoActionButton(container, btn) {
  var b = document.createElement('button');
  b.textContent = btn.label;
  b.className = 'chat-quick-btn';
  b.style.cssText = [
    'background:rgba(253,184,19,0.12)',
    'border:1px solid rgba(253,184,19,0.6)',
    'color:#fdb813',
    'padding:6px 14px',
    'border-radius:20px',
    'cursor:pointer',
    'font-size:12px',
    'transition:all 0.2s ease'
  ].join(';');
  b.addEventListener('mouseover', function () {
    b.style.background = '#fdb813';
    b.style.color = '#000';
    b.style.borderColor = '#fdb813';
  });
  b.addEventListener('mouseout', function () {
    b.style.background = 'rgba(253,184,19,0.12)';
    b.style.color = '#fdb813';
    b.style.borderColor = 'rgba(253,184,19,0.6)';
  });
  b.addEventListener('click', function () {
    var allButtons = container.querySelectorAll('button');
    allButtons.forEach(function (item) { item.disabled = true; });
    appendDemoMessage('user', btn.label, []);
    sendInteractiveMessage(btn.label, btn.id);
  });
  container.appendChild(b);
}

function appendDemoMessage(role, text, buttons, presentation, menuButtonText) {
  var messagesDiv = document.getElementById('demo-messages');
  if (!messagesDiv) return;

  var div = document.createElement('div');
  div.className = 'msg ' + role;

  // Formatter **gras** → <strong>
  var formatted = formatRichText(text);
  // Formatter les retours à la ligne
  div.innerHTML = formatted;
  messagesDiv.appendChild(div);

  // Boutons d'action rapide
  if (buttons && buttons.length > 0) {
    var btnContainer = document.createElement('div');
    btnContainer.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;padding:0 4px;';
    if (presentation === 'list') {
      var menuButton = document.createElement('button');
      menuButton.textContent = menuButtonText || 'Voir les options';
      menuButton.className = 'chat-quick-btn';
      menuButton.style.cssText = 'background:#fdb813;border:1px solid #fdb813;color:#000;padding:7px 16px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:700;';
      menuButton.addEventListener('click', function () {
        menuButton.remove();
        buttons.forEach(function (btn) { createDemoActionButton(btnContainer, btn); });
      });
      btnContainer.appendChild(menuButton);
    } else {
      buttons.forEach(function (btn) { createDemoActionButton(btnContainer, btn); });
    }
    messagesDiv.appendChild(btnContainer);
  }

  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function showDemoTyping() {
  var messagesDiv = document.getElementById('demo-messages');
  if (!messagesDiv) return;
  var div = document.createElement('div');
  div.className = 'msg assistant loading';
  div.id = 'demo-typing';
  div.innerHTML = '<span style="letter-spacing:2px;opacity:0.5">● ● ●</span>';
  messagesDiv.appendChild(div);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function removeDemoTyping() {
  var t = document.getElementById('demo-typing');
  if (t) t.remove();
}

async function sendInteractiveMessage(message, actionId) {
  showDemoTyping();
  try {
    var responsePromise = fetch('/api/v1/chat/interactive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: demoSessionId,
        message: message || '',
        action_id: actionId || null
      })
    });

    // Le message est commite par le serveur avant le traitement IA. Cette
    // requete de lecture le rend visible pendant que l'IA calcule sa reponse.
    window.setTimeout(function () {
      loadStats();
      loadConversations();
    }, 500);

    var res = await responsePromise;

    removeDemoTyping();
    if (!res.ok) {
      appendDemoMessage('assistant', '⚠️ Erreur serveur (' + res.status + ').', []);
      return;
    }
    var data = await res.json();
    appendDemoMessage(
      'assistant',
      data.text,
      data.buttons || [],
      data.presentation,
      data.menu_button_text
    );

    // Mise à jour live du dashboard après chaque échange
    loadStats();
    loadConversations();
  } catch (err) {
    removeDemoTyping();
    appendDemoMessage('assistant', "⚠️ Impossible de joindre l'assistant.", []);
    console.error('Chat error:', err);
  }
}

function initDemoChat() {
  if (demoStarted) return;
  demoStarted = true;
  var messagesDiv = document.getElementById('demo-messages');
  if (messagesDiv) messagesDiv.innerHTML = '';
  // Déclenche le premier message (choix de langue)
  sendInteractiveMessage('', null);
}

function resetDemoChat() {
  demoStarted = false;
  demoSessionId = 'dashboard_' + Math.random().toString(36).substr(2, 9);
  var messagesDiv = document.getElementById('demo-messages');
  if (messagesDiv) messagesDiv.innerHTML = '';
  initDemoChat();
}

// ─── Init DOM ─────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function () {
  var toggleBtn = document.getElementById('demo-toggle');
  var closeBtn = document.getElementById('demo-close');
  var chatWidget = document.getElementById('demo-chat');
  var form = document.getElementById('demo-form');
  var input = document.getElementById('demo-input');
  var loginForm = document.getElementById('login-form');
  var logoutBtn = document.getElementById('logout-btn');
  var loginError = document.getElementById('login-error');
  var notificationBell = document.getElementById('notification-bell');
  var notificationCenter = document.getElementById('notification-center');

  // --- Login ---
  if (loginForm) {
    loginForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      loginError.textContent = '';
      var email = document.getElementById('login-email').value.trim();
      var password = document.getElementById('login-password').value;
      try {
        var res = await fetch('/api/v1/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: email, password: password }),
        });
        if (!res.ok) {
          throw new Error(res.status === 401 ? 'Email ou mot de passe incorrect.' : 'Erreur de connexion');
        }
        var data = await res.json();
        setToken(data.access_token);
        setLoginState();
      } catch (err) {
        loginError.textContent = err.message;
      }
    });
  }

  if (logoutBtn) {
    logoutBtn.addEventListener('click', function () {
      clearToken();
      setLoginState();
    });
  }

  // Le tableau de bord manipule des conversations et des reponses clients :
  // aucune connexion automatique ni identifiant par defaut ne doit etre
  // expose dans le navigateur.
  initFaqManager();
  setLoginState();

  // --- Widget toggle ---
  if (toggleBtn && chatWidget) {
    toggleBtn.addEventListener('click', function () {
      chatWidget.classList.add('open');
      initDemoChat();  // démarre le parcours à l'ouverture
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener('click', function () {
      if (chatWidget) chatWidget.classList.remove('open');
    });
  }

  // Bouton 🔄 Réinitialiser dans le header du widget
  var demoHeader = document.querySelector('.demo-header');
  if (demoHeader && closeBtn) {
    var resetBtn = document.createElement('button');
    resetBtn.textContent = '🔄';
    resetBtn.title = 'Nouvelle conversation';
    resetBtn.style.cssText = 'background:none;border:none;color:#fdb813;cursor:pointer;font-size:15px;padding:2px 6px;';
    resetBtn.addEventListener('click', resetDemoChat);
    demoHeader.insertBefore(resetBtn, closeBtn);
  }

  // --- Envoi texte libre ---
  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var text = (input.value || '').trim();
      if (!text) return;
      appendDemoMessage('user', text, []);
      input.value = '';
      sendInteractiveMessage(text, null);
    });
  }

  // --- Drawer event listeners ---
  var drawerClose = document.getElementById('drawer-close');
  var drawerOverlay = document.getElementById('drawer-overlay');
  var btnResolve = document.getElementById('btn-resolve-claim');

  if (drawerClose) drawerClose.addEventListener('click', closeDrawer);
  if (drawerOverlay) drawerOverlay.addEventListener('click', closeDrawer);

  if (btnResolve) {
    btnResolve.addEventListener('click', async function () {
      var conversationId = btnResolve.dataset.conversationId;
      var label = document.getElementById('btn-resolve-label');
      if (!conversationId || btnResolve.disabled) return;

      btnResolve.disabled = true;
      btnResolve.setAttribute('aria-disabled', 'true');
      if (label) label.textContent = 'Mise à jour…';
      try {
        await fetchJSONWithAuth(
          '/api/v1/dashboard/conversations/' + conversationId + '/resolve',
          { method: 'POST' }
        );
        await Promise.all([loadStats(), loadConversations(), loadNotifications()]);
        await openDrawer(conversationId);
      } catch (err) {
        console.error('Erreur de clôture de l\'escalade:', err);
        alert('Impossible de marquer cette escalade comme traitée. Réessayez.');
        btnResolve.disabled = false;
        btnResolve.setAttribute('aria-disabled', 'false');
        if (label) label.textContent = 'Marquer comme traité';
      }
    });
  }

  // --- Filtres et refresh tableau de bord ---
  loadStats();
  loadConversations();
  loadNotifications();

  setInterval(function () {
    loadConversations();
  }, 5000);
  setInterval(loadStats, 30000);
  setInterval(loadNotifications, 5000);

  if (notificationBell) {
    notificationBell.addEventListener('click', function () {
      var isOpen = notificationBell.getAttribute('aria-expanded') === 'true';
      setNotificationPanelOpen(!isOpen);
      if (!isOpen) loadNotifications();
    });
  }

  document.addEventListener('click', function (event) {
    if (notificationCenter && !notificationCenter.contains(event.target)) {
      setNotificationPanelOpen(false);
    }
  });

  var filterPhone = document.getElementById('filter-phone');
  var filterIntent = document.getElementById('filter-intent');
  var filterStatus = document.getElementById('filter-status');
  var btnRefresh = document.getElementById('btn-refresh');
  var metricsPeriodForm = document.getElementById('metrics-period-form');
  var metricsStartDate = document.getElementById('metrics-start-date');
  var metricsEndDate = document.getElementById('metrics-end-date');
  var metricsPeriodReset = document.getElementById('metrics-period-reset');
  var dashboardExportCsv = document.getElementById('dashboard-export-csv');

  setMetricsPeriodStatus();

  if (metricsStartDate && metricsEndDate) {
    metricsEndDate.min = metricsStartDate.value || '';
    metricsStartDate.addEventListener('change', function () {
      metricsEndDate.min = metricsStartDate.value || '';
    });
  }

  if (metricsPeriodForm) {
    metricsPeriodForm.addEventListener('submit', function (event) {
      event.preventDefault();
      var startDate = metricsStartDate ? metricsStartDate.value : '';
      var endDate = metricsEndDate ? metricsEndDate.value : '';

      if ((startDate && !isIsoDate(startDate)) || (endDate && !isIsoDate(endDate))) {
        setMetricsPeriodFeedback('Saisissez des dates valides.');
        return;
      }
      if (startDate && endDate && startDate > endDate) {
        setMetricsPeriodFeedback('La date de début doit être antérieure ou égale à la date de fin.');
        return;
      }

      metricsPeriod = { startDate: startDate, endDate: endDate };
      setMetricsPeriodStatus();
      setMetricsPeriodFeedback('');
      loadStats();
    });
  }

  if (metricsPeriodReset) {
    metricsPeriodReset.addEventListener('click', function () {
      if (metricsStartDate) metricsStartDate.value = '';
      if (metricsEndDate) {
        metricsEndDate.value = '';
        metricsEndDate.min = '';
      }
      metricsPeriod = { startDate: '', endDate: '' };
      setMetricsPeriodStatus();
      setMetricsPeriodFeedback('');
      loadStats();
    });
  }

  if (dashboardExportCsv) {
    dashboardExportCsv.addEventListener('click', function () {
      exportTicketsAndEscalationsCsv(dashboardExportCsv);
    });
  }

  if (filterPhone) {
    var searchTimer = null;
    filterPhone.addEventListener('input', function () {
      clearTimeout(searchTimer);
      var val = this.value.trim();
      searchTimer = setTimeout(function () {
        currentFilter.phone = val;
        page = 1;
        loadConversations();
      }, 300);
    });
  }

  if (filterIntent) {
    filterIntent.addEventListener('change', function () {
      currentFilter.intent = this.value;
      page = 1;
      loadConversations();
    });
  }

  if (filterStatus) {
    filterStatus.addEventListener('change', function () {
      currentFilter.status = this.value;
      page = 1;
      loadConversations();
    });
  }

  if (btnRefresh) {
    btnRefresh.addEventListener('click', function () {
      loadStats();
      loadConversations();
      loadNotifications();
      loadFaqs();
    });
  }
});
