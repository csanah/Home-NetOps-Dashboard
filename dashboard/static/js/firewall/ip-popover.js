// ── IP Popover ──
let popoverIP = '';

function showIpPopover(event, ip) {
  event.stopPropagation();
  const popover = document.getElementById('ip-popover');
  const ipEl = document.getElementById('ip-popover-ip');
  const hostnameEl = document.getElementById('ip-popover-hostname');

  popoverIP = ip;
  ipEl.textContent = ip;

  // Reset copy icon
  document.getElementById('ip-popover-copy-icon').classList.remove('hidden');
  document.getElementById('ip-popover-check-icon').classList.add('hidden');

  // Resolve hostname
  const cached = hostnameCacheGet(ip);
  if (cached) {
    hostnameEl.textContent = cached;
  } else if (!isExternalIP(ip)) {
    hostnameEl.textContent = 'Local device';
  } else {
    hostnameEl.textContent = 'Resolving...';
    requestDnsResolution(ip);
  }

  // Position near click, clamped to viewport
  const pad = 12;
  let x = event.clientX + pad;
  let y = event.clientY + pad;

  // Show briefly to measure
  popover.classList.remove('hidden');
  const rect = popover.getBoundingClientRect();

  if (x + rect.width > window.innerWidth - pad) {
    x = event.clientX - rect.width - pad;
  }
  if (y + rect.height > window.innerHeight - pad) {
    y = event.clientY - rect.height - pad;
  }
  if (x < pad) x = pad;
  if (y < pad) y = pad;

  popover.style.left = x + 'px';
  popover.style.top = y + 'px';
}

function hideIpPopover() {
  document.getElementById('ip-popover').classList.add('hidden');
  popoverIP = '';
}

function copyPopoverIP() {
  if (!popoverIP) return;
  navigator.clipboard.writeText(popoverIP).then(() => {
    // Flash checkmark
    document.getElementById('ip-popover-copy-icon').classList.add('hidden');
    document.getElementById('ip-popover-check-icon').classList.remove('hidden');
    setTimeout(() => {
      hideIpPopover();
    }, 600);
  });
}

function popoverFilterIP() {
  if (!popoverIP) return;
  document.getElementById('log-filter-input').value = popoverIP;
  setLogFilter(popoverIP);
  hideIpPopover();
}

function popoverLookup() {
  if (!popoverIP) return;
  const ip = popoverIP;
  hideIpPopover();
  switchTab('lookup');
  const input = document.getElementById('lookup-input');
  input.value = ip;
  // Trigger HTMX submit
  htmx.trigger(document.getElementById('lookup-form'), 'submit');
}
