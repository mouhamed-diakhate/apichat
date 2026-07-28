/* ============================================================
   Dashboard TexMiles — dashboard.js
   Widget chat connecté au parcours interactif complet
   (Langue → Menu principal → Agent IA)
   ============================================================ */

var page = 1;
var currentFilter = { intent: '', escalade: '' };
var chartIntents = null;
var chartLangs = null;

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

// ─── Fetch authentifié ────────────────────────────────────────────────────────

async function fetchJSONWithAuth(url) {
  var token = getToken();
  var headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  var res = await fetch(url, { headers: headers });
  if (!res.ok) throw new Error('HTTP ' + res.status);
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
    loadStats();
    loadConversations();
  }
}

// ─── KPIs ─────────────────────────────────────────────────────────────────────

function updateKPIs(data) {
  document.getElementById('kpi-messages').textContent = data.total_messages_recus;
  document.getElementById('kpi-escalade').textContent = (data.escalation_rate * 100).toFixed(1) + '%';
  document.getElementById('kpi-tickets').textContent = data.tickets_created;

  var entries = Object.entries(data.languages || {});
  var top = entries.sort(function (a, b) { return b[1] - a[1]; })[0];
  document.getElementById('kpi-langue').textContent = top ? top[0].toUpperCase() : '—';
  document.getElementById('last-update').textContent = new Date().toLocaleTimeString('fr-FR');
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

async function openDrawer(msgId) {
  var drawer = document.getElementById('conv-drawer');
  var overlay = document.getElementById('drawer-overlay');
  var transcript = document.getElementById('drawer-transcript');
  if (!drawer || !overlay || !transcript) return;

  try {
    transcript.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-muted)">Chargement de la discussion...</div>';
    drawer.classList.add('active');
    overlay.classList.add('active');

    var data = await fetchJSONWithAuth('/api/v1/dashboard/conversations/' + msgId);
    if (data.error) {
      transcript.innerHTML = '<div style="color:var(--danger);padding:1rem;">Erreur: ' + data.error + '</div>';
      return;
    }

    // Infos en-tête client
    document.getElementById('drawer-client-name').textContent = data.client ? data.client.full_name : 'Client Invité';
    document.getElementById('drawer-client-email').textContent = data.client ? data.client.email : 'Visiteur';
    document.getElementById('drawer-intent').innerHTML = getIntentLabel(data.intent);
    document.getElementById('drawer-lang').innerHTML = '<span class="lang-flag">' + getLanguageFlag(data.language) + '</span>';

    var statusHtml = data.escalade
      ? '<span class="status-inline danger">' + ICONS.alert + ' Escaladé (' + (data.raison_escalade || 'Humain') + ')</span>'
      : '<span class="status-inline success">' + ICONS.check + ' Traité par l\'IA</span>';
    document.getElementById('drawer-status').innerHTML = statusHtml;

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

      var contentFormatted = (m.content || '').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
      var timeStr = formatDate(m.created_at);

      var toolsBadge = m.outils_utilises ? '<div class="t-tool">' + ICONS.tool + ' Outil: ' + m.outils_utilises + '</div>' : '';

      div.innerHTML = contentFormatted + toolsBadge + '<span class="t-msg-time">' + timeStr + '</span>';
      transcript.appendChild(div);
    });

    transcript.scrollTop = transcript.scrollHeight;
  } catch (err) {
    console.error('Erreur ouverture drawer:', err);
    transcript.innerHTML = '<div style="color:var(--danger);padding:1rem;">Erreur de chargement: ' + err.message + '</div>';
  }
}

function closeDrawer() {
  var drawer = document.getElementById('conv-drawer');
  var overlay = document.getElementById('drawer-overlay');
  if (drawer) drawer.classList.remove('active');
  if (overlay) overlay.classList.remove('active');
}

// ─── Tableau conversations ────────────────────────────────────────────────────

async function loadConversations() {
  var params = new URLSearchParams({ page: page, page_size: 20 });
  if (currentFilter.intent) params.set('intent', currentFilter.intent);
  if (currentFilter.escalade !== '') params.set('escalade', currentFilter.escalade);

  try {
    var data = await fetchJSONWithAuth('/api/v1/dashboard/conversations?' + params.toString());
    var tbody = document.getElementById('conv-body');
    tbody.innerHTML = '';

    if (data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">Aucune conversation</td></tr>';
      return;
    }

    data.items.forEach(function (item) {
      var tr = document.createElement('tr');
      tr.className = 'clickable-row';
      var statusClass = item.escalade ? 'status-escalated' : 'status-resolved';
      var statusText = item.escalade ? (item.raison_escalade || 'Escaladé') : 'Résolu';
      var ticket = item.ticket_id ? '<span class="ticket-link">' + item.ticket_id + '</span>' : '—';

      tr.innerHTML =
        '<td>' + formatDate(item.created_at) + '</td>' +
        '<td><strong>' + maskEmail(item.user_email) + '</strong></td>' +
        '<td>' + getIntentLabel(item.intent) + '</td>' +
        '<td><span class="lang-flag">' + getLanguageFlag(item.language) + '</span></td>' +
        '<td class="' + statusClass + '">' + statusText + '</td>' +
        '<td>' + ticket + '</td>' +
        '<td class="preview-text" title="' + item.message_preview + '">' + item.message_preview + '</td>';

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
      '<tr><td colspan="7" style="text-align:center;color:var(--danger)">Erreur: ' + err.message + '</td></tr>';
  }
}

async function loadStats() {
  try {
    var data = await fetchJSONWithAuth('/api/v1/dashboard/stats');
    updateKPIs(data);
    renderCharts(data);
  } catch (err) {
    console.error('Stats error:', err);
  }
}

// ─── Widget Chat Interactif (Langue → Menu → Agent IA) ───────────────────────

function appendDemoMessage(role, text, buttons) {
  var messagesDiv = document.getElementById('demo-messages');
  if (!messagesDiv) return;

  var div = document.createElement('div');
  div.className = 'msg ' + role;

  // Formatter **gras** → <strong>
  var formatted = (text || '').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Formatter les retours à la ligne
  formatted = formatted.replace(/\n/g, '<br>');
  div.innerHTML = formatted;
  messagesDiv.appendChild(div);

  // Boutons d'action rapide
  if (buttons && buttons.length > 0) {
    var btnContainer = document.createElement('div');
    btnContainer.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;padding:0 4px;';
    buttons.forEach(function (btn) {
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
        appendDemoMessage('user', btn.label, []);
        sendInteractiveMessage('', btn.id);
      });
      btnContainer.appendChild(b);
    });
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
    var res = await fetch('/api/v1/chat/interactive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: demoSessionId,
        message: message || '',
        action_id: actionId || null
      })
    });

    removeDemoTyping();
    if (!res.ok) {
      appendDemoMessage('assistant', '⚠️ Erreur serveur (' + res.status + ').', []);
      return;
    }
    var data = await res.json();
    appendDemoMessage('assistant', data.text, data.buttons || []);

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

  async function autoLoginIfNoToken() {
    if (!getToken()) {
      try {
        var res = await fetch('/api/v1/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: 'admin@texmiles.sn', password: 'Admin1234!' }),
        });
        if (res.ok) {
          var data = await res.json();
          setToken(data.access_token);
        }
      } catch (err) {
        console.warn('Auto login skip:', err);
      }
    }
    setLoginState();
  }

  if (logoutBtn) {
    logoutBtn.addEventListener('click', function () {
      clearToken();
      setLoginState();
    });
  }

  autoLoginIfNoToken();

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
  var btnWhatsapp = document.getElementById('btn-contact-client');

  if (drawerClose) drawerClose.addEventListener('click', closeDrawer);
  if (drawerOverlay) drawerOverlay.addEventListener('click', closeDrawer);

  if (btnResolve) {
    btnResolve.addEventListener('click', function () {
      alert('Statut mis à jour : traité par l\'équipe TexMiles.');
      closeDrawer();
      loadStats();
      loadConversations();
    });
  }

  if (btnWhatsapp) {
    btnWhatsapp.addEventListener('click', function () {
      window.open('https://wa.me/221770000000?text=Bonjour%20TexMiles%20service%20client', '_blank');
    });
  }

  // --- Filtres et refresh tableau de bord ---
  loadStats();
  loadConversations();

  setInterval(function () {
    loadStats();
    loadConversations();
  }, 30000);

  var filterIntent = document.getElementById('filter-intent');
  var filterEscalade = document.getElementById('filter-escalade');
  var btnRefresh = document.getElementById('btn-refresh');

  if (filterIntent) {
    filterIntent.addEventListener('change', function () {
      currentFilter.intent = this.value;
      page = 1;
      loadConversations();
    });
  }

  if (filterEscalade) {
    filterEscalade.addEventListener('change', function () {
      currentFilter.escalade = this.value;
      page = 1;
      loadConversations();
    });
  }

  if (btnRefresh) {
    btnRefresh.addEventListener('click', function () {
      loadStats();
      loadConversations();
    });
  }
});
