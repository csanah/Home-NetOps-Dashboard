// ── Device Picker ──
let currentDeviceStatusFilter = 'all';
let currentDeviceConnectionFilter = 'all';

function selectDevice(ip, el) {
  document.querySelectorAll('.device-row').forEach(r => r.classList.remove('bg-blue-50', 'dark:bg-blue-900/20', 'ring-1', 'ring-blue-500'));
  el.classList.add('bg-blue-50', 'dark:bg-blue-900/20', 'ring-1', 'ring-blue-500');

  // Put IP in the Live Logs filter field and switch to that tab
  document.getElementById('log-filter-input').value = ip;
  switchTab('logs');
  document.getElementById('log-filter-input').focus();
}

function filterDevices() {
  const query = (document.getElementById('device-filter')?.value || '').toLowerCase();
  const statusFilter = currentDeviceStatusFilter || 'all';
  const connectionFilter = currentDeviceConnectionFilter || 'all';
  const rows = document.querySelectorAll('.device-row');
  const groups = document.querySelectorAll('.device-group');

  rows.forEach(row => {
    const name = (row.dataset.name || '').toLowerCase();
    const ip = (row.dataset.ip || '').toLowerCase();
    const isOnline = row.dataset.online === 'true';
    const wired = row.dataset.wired; // 'true', 'false', or 'unknown'

    const matchesText = !query || name.includes(query) || ip.includes(query);
    const matchesStatus = statusFilter === 'all' ||
      (statusFilter === 'online' && isOnline) ||
      (statusFilter === 'offline' && !isOnline);
    const matchesConnection = connectionFilter === 'all' ||
      (connectionFilter === 'wired' && wired === 'true') ||
      (connectionFilter === 'wireless' && wired === 'false');

    row.style.display = (matchesText && matchesStatus && matchesConnection) ? '' : 'none';
  });

  groups.forEach(group => {
    const visible = group.querySelectorAll('.device-row:not([style*="display: none"])');
    const header = group.querySelector('div:first-child');
    if (header) header.style.display = visible.length ? '' : 'none';
  });
}

function refreshClients() {
  const btn = document.getElementById('btn-refresh-clients');
  btn.textContent = 'Loading...';
  btn.disabled = true;

  fetch('/firewall/clients')
    .then(r => r.json())
    .then(clients => {
      renderDeviceList(clients);
      btn.innerHTML = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg> Refresh';
      btn.disabled = false;
    })
    .catch(() => {
      btn.innerHTML = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg> Refresh';
      btn.disabled = false;
    });
}

function renderDeviceList(clients) {
  const container = document.getElementById('device-list');
  if (!clients.length) {
    container.innerHTML = '<div class="px-4 py-6 text-center text-sm text-gray-400">No devices found</div>';
    updateDeviceCountBadge(0, 0);
    return;
  }

  const groups = { phone: [], computer: [], other: [] };
  let totalOnline = 0;
  clients.forEach(c => {
    (groups[c.category] || groups.other).push(c);
    if (c.online) totalOnline++;
  });

  updateDeviceCountBadge(totalOnline, clients.length);

  const icons = {
    phone: { svg: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z"/>', bg: 'bg-blue-100 dark:bg-blue-900/40', fg: 'text-blue-600 dark:text-blue-400', label: 'Phones' },
    computer: { svg: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>', bg: 'bg-purple-100 dark:bg-purple-900/40', fg: 'text-purple-600 dark:text-purple-400', label: 'Computers' },
    other: { svg: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.141 0M1.394 9.393c5.857-5.858 15.355-5.858 21.213 0"/>', bg: 'bg-gray-100 dark:bg-gray-700', fg: 'text-gray-500 dark:text-gray-400', label: 'Other Devices' }
  };

  let html = '';
  for (const [key, items] of Object.entries(groups)) {
    if (!items.length) continue;
    const ic = icons[key];
    const groupOnline = items.filter(d => d.online).length;
    html += `<div class="device-group" data-group="${key}">`;
    html += `<div class="px-4 py-2 bg-gray-50 dark:bg-gray-750 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide border-b border-gray-100 dark:border-gray-700/50 flex items-center gap-1.5">
      <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">${ic.svg}</svg>
      ${ic.label} <span class="text-gray-400 font-normal">(${groupOnline}/${items.length})</span>
    </div>`;
    items.forEach(d => {
      const safeName = d.name.replace(/</g, '&lt;').replace(/>/g, '&gt;');
      const isOnline = !!d.online;
      const statusDotColor = isOnline ? 'bg-green-400' : 'bg-gray-400';
      const opacityClass = isOnline ? '' : ' opacity-60';
      const wiredVal = d.wired === true ? 'true' : (d.wired === false ? 'false' : 'unknown');
      const connIcon = d.wired === true
        ? '<svg class="w-3 h-3 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" title="Wired"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>'
        : (d.wired === false
          ? '<svg class="w-3 h-3 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" title="Wireless"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.141 0M1.394 9.393c5.857-5.858 15.355-5.858 21.213 0"/></svg>'
          : '');
      html += `<button onclick="selectDevice('${d.ip}', this)" data-name="${safeName}" data-ip="${d.ip}" data-online="${isOnline}" data-wired="${wiredVal}"
        class="device-row w-full text-left px-4 py-2.5 flex items-center gap-3 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors border-b border-gray-50 dark:border-gray-700/30 last:border-0${opacityClass}">
        <div class="relative shrink-0">
          <div class="w-8 h-8 rounded-full ${ic.bg} flex items-center justify-center">
            <svg class="w-4 h-4 ${ic.fg}" fill="none" stroke="currentColor" viewBox="0 0 24 24">${ic.svg}</svg>
          </div>
          <span class="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-white dark:border-gray-800 ${statusDotColor}"></span>
        </div>
        <div class="min-w-0 flex-1">
          <div class="text-sm font-medium truncate flex items-center gap-1">${safeName} ${connIcon}</div>
          <div class="text-xs text-gray-400 font-mono">${d.ip || 'No IP'}</div>
        </div>
      </button>`;
    });
    html += '</div>';
  }
  container.innerHTML = html;

  // Re-apply current filters
  filterDevices();
}

function updateDeviceCountBadge(online, total) {
  const badge = document.getElementById('device-count-badge');
  if (badge) badge.textContent = online + '/' + total;
}

function filterDeviceStatus(status) {
  currentDeviceStatusFilter = status;

  // Update pill styling
  document.querySelectorAll('.status-filter-btn').forEach(btn => {
    if (btn.dataset.statusFilter === status) {
      btn.classList.add('bg-blue-600', 'text-white');
      btn.classList.remove('text-gray-500', 'dark:text-gray-400');
    } else {
      btn.classList.remove('bg-blue-600', 'text-white');
      btn.classList.add('text-gray-500', 'dark:text-gray-400');
    }
  });

  filterDevices();
}

function filterDeviceConnection(type) {
  currentDeviceConnectionFilter = type;

  document.querySelectorAll('.connection-filter-btn').forEach(btn => {
    if (btn.dataset.connectionFilter === type) {
      btn.classList.add('bg-blue-600', 'text-white');
      btn.classList.remove('text-gray-500', 'dark:text-gray-400');
    } else {
      btn.classList.remove('bg-blue-600', 'text-white');
      btn.classList.add('text-gray-500', 'dark:text-gray-400');
    }
  });

  filterDevices();
}
