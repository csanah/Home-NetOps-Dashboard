// ── Tab Switching ──
function switchTab(name) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.remove('bg-white', 'dark:bg-gray-600', 'text-gray-900', 'dark:text-white', 'shadow-sm');
    b.classList.add('text-gray-600', 'dark:text-gray-300');
  });
  document.getElementById('tab-' + name).classList.remove('hidden');
  const btn = document.querySelector(`.tab-btn[data-tab="${name}"]`);
  btn.classList.add('bg-white', 'dark:bg-gray-600', 'text-gray-900', 'dark:text-white', 'shadow-sm');
  btn.classList.remove('text-gray-600', 'dark:text-gray-300');

  if (name === 'rules' && !rulesLoaded) {
    refreshRules();
  }
}

// ── Live Log Stream ──
const fwSocket = io('/firewall');
const logContainer = document.getElementById('log-container');
const logTbody = document.getElementById('log-tbody');

// Event delegation for IP clicks (instead of inline onclick per row)
logTbody.addEventListener('click', function(e) {
  const td = e.target.closest('td[data-ip-src], td[data-ip-dst]');
  if (!td) return;
  const ip = td.dataset.ipSrc || td.dataset.ipDst;
  if (ip && ip !== '-') {
    showIpPopover(e, ip);
  }
});

const streamStatus = document.getElementById('stream-status');
const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const MAX_LINES = 500;

let logFilterIP = '';
let placeholderCleared = false;
let currentMode = 'all';  // 'all' or 'blocked'
let currentScope = 'both';  // 'both', 'local', 'external'
let streamRunning = false;

fwSocket.on('log_line', function(data) {
  if (!placeholderCleared) {
    logTbody.innerHTML = '';
    placeholderCleared = true;
  }
  startPpsCounter();

  const raw = data.line;

  if (paused) {
    // Still count stats but don't render
    pauseBuffer.push(raw);
    const parsed = parseLine(raw);
    stats.total++;
    ppsCount++;
    if (parsed.action === 'DROP' || parsed.action === 'REJECT') stats.blocked++;
    else if (parsed.action === 'ACCEPT' || parsed.action === 'ALLOW') stats.allowed++;
    if (parsed.src) uniqueIPs.add(parsed.src);
    if (parsed.dst) uniqueIPs.add(parsed.dst);
    updateStatsDisplay();
    const badge = document.getElementById('pause-badge');
    if (badge) badge.textContent = pauseBuffer.length + ' buffered';
    return;
  }

  if (currentSpeed === 'realtime') {
    // rAF batching: collect lines, flush once per animation frame
    rafBuffer.push(raw);
    if (!rafScheduled) {
      rafScheduled = true;
      requestAnimationFrame(flushRafBuffer);
    }
  } else {
    renderBuffer.push(raw);
  }
});

// ── DNS Result Handler ──
fwSocket.on('dns_result', function(data) {
  const { ip, hostname } = data;
  if (!ip || !hostname) return;
  hostnameCacheSet(ip, hostname);

  // O(1) update via IP→Element maps instead of querySelectorAll
  const srcSet = ipSrcElements.get(ip);
  if (srcSet) {
    srcSet.forEach(td => { td.innerHTML = formatIpWithHostname(ip, 'text-cyan-400'); });
  }
  const dstSet = ipDstElements.get(ip);
  if (dstSet) {
    dstSet.forEach(td => { td.innerHTML = formatIpWithHostname(ip, 'text-yellow-400'); });
  }

  // Live-update popover if showing this IP
  if (popoverIP === ip) {
    document.getElementById('ip-popover-hostname').textContent = hostname;
  }
});

// ── Server Icon ──
const serverIcon = document.getElementById('server-icon');

function updateServerIcon(status) {
  serverIcon.classList.remove('bg-red-500', 'bg-green-500', 'bg-yellow-500');
  if (status === 'connected') {
    serverIcon.classList.add('bg-green-500');
    serverIcon.title = 'Stream: Running (right-click for options)';
  } else if (status === 'connecting') {
    serverIcon.classList.add('bg-yellow-500');
    serverIcon.title = 'Stream: Connecting...';
  } else {
    serverIcon.classList.add('bg-red-500');
    serverIcon.title = 'Stream: Stopped (click to start, right-click for options)';
  }
}

function showServerMenu(e) {
  e.preventDefault();
  const menu = document.getElementById('server-menu');
  menu.classList.remove('hidden');
  menu.style.left = e.pageX + 'px';
  menu.style.top = e.pageY + 'px';
}

function hideServerMenu() {
  document.getElementById('server-menu').classList.add('hidden');
}

document.addEventListener('click', function(e) {
  const menu = document.getElementById('server-menu');
  if (!menu.contains(e.target) && e.target.id !== 'server-icon') {
    menu.classList.add('hidden');
  }
  // Dismiss IP popover on outside click
  const popover = document.getElementById('ip-popover');
  if (!popover.contains(e.target)) {
    hideIpPopover();
  }
});

fwSocket.on('stream_status', function(data) {
  streamStatus.textContent = data.status.charAt(0).toUpperCase() + data.status.slice(1);
  if (data.message) {
    streamStatus.textContent += ': ' + data.message;
  }

  if (data.status === 'connected') {
    streamStatus.className = 'text-xs text-green-400';
    const modeLabel = data.mode === 'blocked' ? ' (blocked only)' : ' (all traffic)';
    streamStatus.textContent += modeLabel;
    btnStart.disabled = true;
    btnStop.disabled = false;
    streamRunning = true;
    updateServerIcon('connected');
    if (!placeholderCleared) {
      logTbody.innerHTML = '';
      placeholderCleared = true;
    }
  } else {
    streamStatus.className = 'text-xs text-gray-400';
    btnStart.disabled = false;
    btnStop.disabled = true;
    streamRunning = false;
    updateServerIcon('disconnected');
  }
});

function startStream() {
  fwSocket.emit('start_stream', { mode: currentMode, filter_ip: logFilterIP || null, scope: currentScope });
  streamStatus.textContent = 'Connecting...';
  updateServerIcon('connecting');
}

function stopStream() {
  fwSocket.emit('stop_stream');
}

function restartStream() {
  if (streamRunning) {
    fwSocket.emit('stop_stream');
    setTimeout(() => { startStream(); }, 300);
  }
}

function setMode(mode) {
  currentMode = mode;
  const btnBlocked = document.getElementById('btn-blocked-only');

  if (mode === 'blocked') {
    btnBlocked.classList.remove('bg-gray-600', 'hover:bg-gray-700');
    btnBlocked.classList.add('bg-red-600', 'hover:bg-red-700');
  } else {
    btnBlocked.classList.remove('bg-red-600', 'hover:bg-red-700');
    btnBlocked.classList.add('bg-gray-600', 'hover:bg-gray-700');
  }
  restartStream();
}

function toggleBlockedOnly() {
  setMode(currentMode === 'blocked' ? 'all' : 'blocked');
}

function setScope(scope) {
  currentScope = scope;
  ['both', 'local', 'external'].forEach(s => {
    const btn = document.getElementById('btn-scope-' + s);
    if (s === scope) {
      btn.classList.add('bg-blue-600', 'text-white');
      btn.classList.remove('text-gray-500', 'dark:text-gray-400');
    } else {
      btn.classList.remove('bg-blue-600', 'text-white');
      btn.classList.add('text-gray-500', 'dark:text-gray-400');
    }
  });
  restartStream();
}

function clearLogs() {
  logTbody.innerHTML = '';
  placeholderCleared = true;
  renderBuffer = [];
  pauseBuffer = [];
  rafBuffer = [];
  hostnameCache.clear();
  dnsRequestQueue.clear();
  ipSrcElements.clear();
  ipDstElements.clear();
  resetStats();
}

// ── Log Filter (server-side — restarts stream) ──
function setLogFilter(ip) {
  const prevIP = logFilterIP;
  logFilterIP = ip;
  const badge = document.getElementById('filter-badge');
  const badgeText = document.getElementById('filter-badge-text');

  if (ip) {
    badge.style.display = 'flex';
    badgeText.textContent = ip;
  } else {
    badge.style.display = 'none';
  }

  // Restart stream with new filter if it changed while running
  if (prevIP !== ip) {
    restartStream();
  }
}

function clearLogFilter() {
  document.getElementById('log-filter-input').value = '';
  document.querySelectorAll('.device-row').forEach(r => r.classList.remove('bg-blue-50', 'dark:bg-blue-900/20', 'ring-1', 'ring-blue-500'));
  setLogFilter('');
}

function applyLogFilterInput() {
  const val = document.getElementById('log-filter-input').value.trim();
  setLogFilter(val);
}

// ── Socket.IO Reconnect Handlers ──
let wasStreamRunning = false;
let lastStreamConfig = { mode: 'all', filter_ip: null, scope: 'both' };

fwSocket.on('connect', function() {
  streamStatus.textContent = 'Socket connected';
  streamStatus.className = 'text-xs text-green-400';
  // Auto-restart stream if it was running before disconnect
  if (wasStreamRunning) {
    wasStreamRunning = false;
    setTimeout(() => {
      startStream();
    }, 500);
  }
});

fwSocket.on('disconnect', function() {
  if (streamRunning) {
    wasStreamRunning = true;
  }
  streamRunning = false;
  streamStatus.textContent = 'Socket disconnected — reconnecting...';
  streamStatus.className = 'text-xs text-red-400';
  updateServerIcon('disconnected');
  btnStart.disabled = false;
  btnStop.disabled = true;
});

fwSocket.on('connect_error', function(err) {
  streamStatus.textContent = 'Connection error — retrying...';
  streamStatus.className = 'text-xs text-red-400';
  updateServerIcon('disconnected');
});

// ── Connection Timeout for Stream Start ──
let streamConnectTimeout = null;

(function() {
  const origStartStream = startStream;
  startStream = function() {
    // Save config for auto-reconnect
    lastStreamConfig = { mode: currentMode, filter_ip: logFilterIP || null, scope: currentScope };
    origStartStream();
    // Set 15s timeout waiting for stream_status
    if (streamConnectTimeout) clearTimeout(streamConnectTimeout);
    streamConnectTimeout = setTimeout(() => {
      if (!streamRunning) {
        streamStatus.textContent = 'Connection timed out';
        streamStatus.className = 'text-xs text-red-400';
        updateServerIcon('disconnected');
        btnStart.disabled = false;
        btnStop.disabled = true;
      }
    }, 15000);
  };
})();

// Clear timeout when stream connects successfully
fwSocket.on('stream_status', function clearConnectTimeout() {
  if (streamConnectTimeout) {
    clearTimeout(streamConnectTimeout);
    streamConnectTimeout = null;
  }
});

// ── DOM Event Bindings (replaces inline handlers) ──
(function() {
  // Tab buttons
  document.querySelectorAll('.tab-btn[data-tab]').forEach(function(btn) {
    btn.addEventListener('click', function() { switchTab(this.dataset.tab); });
  });

  // Server icon
  serverIcon.addEventListener('click', function() { startStream(); });
  serverIcon.addEventListener('contextmenu', function(e) { showServerMenu(e); });

  // Server menu (event delegation)
  document.getElementById('server-menu').addEventListener('click', function(e) {
    var btn = e.target.closest('button[data-action]');
    if (!btn) return;
    var action = btn.dataset.action;
    if (action === 'start') { startStream(); }
    else if (action === 'stop') { stopStream(); }
    else if (action === 'restart') { stopStream(); setTimeout(startStream, 500); }
    hideServerMenu();
  });

  // Start / Stop / Clear
  btnStart.addEventListener('click', function() { startStream(); });
  btnStop.addEventListener('click', function() { stopStream(); });
  document.getElementById('btn-clear-logs').addEventListener('click', clearLogs);

  // Filter input + buttons
  document.getElementById('log-filter-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') applyLogFilterInput();
  });
  document.getElementById('btn-apply-filter').addEventListener('click', applyLogFilterInput);
  document.getElementById('btn-clear-filter').addEventListener('click', clearLogFilter);

  // Blocked only
  document.getElementById('btn-blocked-only').addEventListener('click', toggleBlockedOnly);

  // Scope buttons
  ['both', 'local', 'external'].forEach(function(s) {
    document.getElementById('btn-scope-' + s).addEventListener('click', function() { setScope(s); });
  });

  // Pause + Auto-scroll
  document.getElementById('btn-pause').addEventListener('click', togglePause);
  document.getElementById('btn-autoscroll').addEventListener('click', toggleAutoScroll);

  // Speed buttons
  ['realtime', 'fast', 'normal', 'slow', 'batch'].forEach(function(s) {
    document.getElementById('btn-speed-' + s).addEventListener('click', function() { setSpeed(s); });
  });

  // IP Popover
  document.getElementById('ip-popover').addEventListener('click', function(e) { e.stopPropagation(); });
  document.getElementById('ip-popover-copy-btn').addEventListener('click', copyPopoverIP);
  document.getElementById('btn-popover-filter').addEventListener('click', popoverFilterIP);
  document.getElementById('btn-popover-lookup').addEventListener('click', popoverLookup);

  // Device picker
  document.getElementById('btn-refresh-clients').addEventListener('click', refreshClients);

  document.querySelectorAll('.status-filter-btn').forEach(function(btn) {
    btn.addEventListener('click', function() { filterDeviceStatus(this.dataset.statusFilter); });
  });
  document.querySelectorAll('.connection-filter-btn').forEach(function(btn) {
    btn.addEventListener('click', function() { filterDeviceConnection(this.dataset.connectionFilter); });
  });

  document.getElementById('device-filter').addEventListener('input', filterDevices);

  // Device row clicks (event delegation)
  document.getElementById('device-list').addEventListener('click', function(e) {
    var row = e.target.closest('.device-row');
    if (row) selectDevice(row.dataset.ip, row);
  });

  // Refresh rules
  document.getElementById('btn-refresh-rules').addEventListener('click', refreshRules);

  // Keyboard shortcut help
  document.getElementById('shortcut-help').addEventListener('click', toggleShortcutHelp);
  document.getElementById('shortcut-help-dialog').addEventListener('click', function(e) { e.stopPropagation(); });
  document.getElementById('btn-close-shortcuts').addEventListener('click', toggleShortcutHelp);
})();
