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

async function loadConversations() {
  var params = new URLSearchParams({ page: page, page_size: 20 });
  if (currentFilter.intent) params.set('intent', currentFilter.intent);
  if (currentFilter.escalade !== '') params.set('escalade', currentFilter.escalade);

  try {
    var data = await fetchJSONWithAuth('/api/v1/dashboard/conversations?' + params.toString());
    var tbody = document.getElementById('conv-body');
    tbody.innerHTML = '';

    if (data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Aucune conversation</td></tr>';
      return;
    }

    data.items.forEach(function (item) {
      var tr = document.createElement('tr');
      var statusClass = item.escalade ? 'status-escalated' : 'status-resolved';
      var statusText = item.escalade ? (item.raison_escalade || 'Escaladé') : 'Résolu';
      var ticket = item.ticket_id ? '<span class="ticket-link">' + item.ticket_id + '</span>' : '—';

      tr.innerHTML =
        '<td>' + formatDate(item.created_at) + '</td>' +
        '<td>' + maskEmail(item.user_email) + '</td>' +
        '<td>' + (item.intent || '—') + '</td>' +
        '<td class="' + statusClass + '">' + statusText + '</td>' +
        '<td>' + ticket + '</td>' +
        '<td class="preview-text" title="' + item.message_preview + '">' + item.message_preview + '</td>';
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
      '<tr><td colspan="6" style="text-align:center;color:var(--danger)">Erreur: ' + err.message + '</td></tr>';
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
