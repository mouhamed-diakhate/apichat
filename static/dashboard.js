var page = 1;
var currentFilter = { intent: '', escalade: '' };
var chartIntents = null;
var chartLangs = null;

function getToken() {
  var match = document.cookie.match(/access_token=([^;]+)/);
  return match ? match[1] : null;
}

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

async function fetchJSONWithAuth(url) {
  var token = getToken();
  var headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  var res = await fetch(url, { headers: headers });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

function setToken(token) {
  document.cookie = 'access_token=' + token + '; path=/';
}

function clearToken() {
  document.cookie = 'access_token=; Max-Age=0; path=/';
}

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

function updateKPIs(data) {
  document.getElementById('kpi-messages').textContent = data.total_messages_recus;
  document.getElementById('kpi-escalade').textContent = (data.escalation_rate * 100).toFixed(1) + '%';
  document.getElementById('kpi-tickets').textContent = data.tickets_created;

  var entries = Object.entries(data.languages || {});
  var top = entries.sort(function (a, b) { return b[1] - a[1]; })[0];
  document.getElementById('kpi-langue').textContent = top ? top[0].toUpperCase() : '—';
  document.getElementById('last-update').textContent = new Date().toLocaleTimeString('fr-FR');
}

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

document.addEventListener('DOMContentLoaded', function () {
  var toggleBtn = document.getElementById('demo-toggle');
  var closeBtn = document.getElementById('demo-close');
  var chatWidget = document.getElementById('demo-chat');
  var form = document.getElementById('demo-form');
  var input = document.getElementById('demo-input');
  var messagesDiv = document.getElementById('demo-messages');
  var loginForm = document.getElementById('login-form');
  var logoutBtn = document.getElementById('logout-btn');
  var loginError = document.getElementById('login-error');

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
          var errorText = 'Erreur de connexion';
          if (res.status === 401) errorText = 'Email ou mot de passe incorrect.';
          throw new Error(errorText);
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

  setLoginState();

  if (toggleBtn && chatWidget) {
    toggleBtn.addEventListener('click', function () {
      chatWidget.classList.add('open');
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener('click', function () {
      if (chatWidget) {
        chatWidget.classList.remove('open');
      }
    });
  }

  if (chatWidget) {
    chatWidget.addEventListener('click', function (event) {
      var target = event.target;
      while (target && target.nodeType !== 1) {
        target = target.parentNode;
      }
      if (target && target.closest('#demo-close')) {
        chatWidget.classList.remove('open');
      }
    });
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) return;

    var userMsg = document.createElement('div');
    userMsg.className = 'msg user';
    userMsg.textContent = text;
    messagesDiv.appendChild(userMsg);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    var loadingMsg = document.createElement('div');
    loadingMsg.className = 'msg loading';
    loadingMsg.textContent = '…';
    messagesDiv.appendChild(loadingMsg);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    input.value = '';
    input.disabled = true;
    form.querySelector('button').disabled = true;

    try {
      var token = getToken();
      if (!token) {
        loadingMsg.textContent = 'Non connecté. Ouvrez /dashboard après connexion.';
        input.disabled = false;
        form.querySelector('button').disabled = false;
        return;
      }

      var res = await fetch('/api/v1/chat/message', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + token,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ content: text })
      });

      if (!res.ok) throw new Error('HTTP ' + res.status);
      var data = await res.json();
      loadingMsg.remove();

      var assistantMsg = document.createElement('div');
      assistantMsg.className = 'msg assistant';
      assistantMsg.textContent = data.content || '(réponse vide)';
      messagesDiv.appendChild(assistantMsg);

      if (data.ticket_id) {
        var ticketMsg = document.createElement('div');
        ticketMsg.className = 'msg assistant';
        ticketMsg.textContent = 'Ticket créé : ' + data.ticket_id;
        ticketMsg.style.fontSize = '0.8rem';
        messagesDiv.appendChild(ticketMsg);
      }

      messagesDiv.scrollTop = messagesDiv.scrollHeight;
      loadStats();
      loadConversations();

    } catch (err) {
      loadingMsg.textContent = 'Erreur : ' + err.message;
    }

    input.disabled = false;
    form.querySelector('button').disabled = false;
    input.focus();
  });

  loadStats();
  loadConversations();

  setInterval(function () {
    loadStats();
    loadConversations();
  }, 30000);

  document.getElementById('filter-intent').addEventListener('change', function () {
    currentFilter.intent = this.value;
    page = 1;
    loadConversations();
  });

  document.getElementById('filter-escalade').addEventListener('change', function () {
    currentFilter.escalade = this.value;
    page = 1;
    loadConversations();
  });

  document.getElementById('btn-refresh').addEventListener('click', function () {
    loadStats();
    loadConversations();
  });
});
