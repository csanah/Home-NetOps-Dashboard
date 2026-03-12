(function() {
  // ── CSRF token for HTMX and fetch requests ──
  var meta = document.querySelector('meta[name="csrf-token"]');
  if (meta) {
    var token = meta.getAttribute('content');
    document.body.setAttribute('hx-headers', JSON.stringify({"X-CSRFToken": token}));
    var _origFetch = window.fetch;
    window.fetch = function(url, opts) {
      opts = opts || {};
      if (opts.method && opts.method !== 'GET' && opts.method !== 'HEAD') {
        opts.headers = opts.headers || {};
        if (opts.headers instanceof Headers) {
          if (!opts.headers.has('X-CSRFToken')) opts.headers.set('X-CSRFToken', token);
        } else {
          if (!opts.headers['X-CSRFToken']) opts.headers['X-CSRFToken'] = token;
        }
      }
      return _origFetch.call(this, url, opts);
    };
  }

  // ── Mobile Navigation ──
  function closeMobileNav() {
    document.getElementById('sidebar').classList.add('-translate-x-full');
    document.getElementById('sidebar-overlay').classList.add('hidden');
  }

  document.getElementById('mobile-menu-btn').addEventListener('click', function() {
    var sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('-translate-x-full');
    var overlay = document.getElementById('sidebar-overlay');
    if (sidebar.classList.contains('-translate-x-full')) {
      overlay.classList.add('hidden');
    } else {
      overlay.classList.remove('hidden');
    }
  });

  document.getElementById('sidebar-overlay').addEventListener('click', function() {
    closeMobileNav();
  });

  var sidebarCloseBtn = document.getElementById('sidebar-close-btn');
  if (sidebarCloseBtn) {
    sidebarCloseBtn.addEventListener('click', closeMobileNav);
  }

  // Nav links — close mobile nav on click (event delegation)
  var sidebarNav = document.querySelector('#sidebar nav');
  if (sidebarNav) {
    sidebarNav.addEventListener('click', function(e) {
      if (e.target.closest('a.nav-link, button.nav-link')) closeMobileNav();
    });
  }

  // Mobile theme toggle
  var mobileToggle = document.getElementById('theme-toggle-mobile');
  if (mobileToggle) {
    mobileToggle.addEventListener('click', function() {
      document.documentElement.classList.toggle('dark');
      localStorage.setItem('theme', document.documentElement.classList.contains('dark') ? 'dark' : 'light');
    });
  }

  // ── Restart Server Modal ──
  function showRestartModal() {
    document.getElementById('restart-modal').classList.remove('hidden');
    document.getElementById('restart-confirm').classList.remove('hidden');
    document.getElementById('restart-progress').classList.add('hidden');
  }
  function hideRestartModal() {
    document.getElementById('restart-modal').classList.add('hidden');
  }
  function doRestart() {
    document.getElementById('restart-confirm').classList.add('hidden');
    document.getElementById('restart-progress').classList.remove('hidden');
    document.getElementById('restart-status').textContent = 'Shutting down server';
    fetch('/api/restart', { method: 'POST' }).then(function() {
      document.getElementById('restart-status').textContent = 'Waiting for server to come back...';
      pollRestart();
    }).catch(function() {
      document.getElementById('restart-status').textContent = 'Waiting for server to come back...';
      pollRestart();
    });
  }
  function pollRestart() {
    var attempts = 0, maxAttempts = 30;
    setTimeout(function poll() {
      fetch('/api/health', { cache: 'no-store' }).then(function(r) {
        if (r.ok) {
          document.getElementById('restart-status').textContent = 'Server is back!';
          setTimeout(function() { location.reload(); }, 500);
        } else { retry(); }
      }).catch(function() { retry(); });
      function retry() {
        attempts++;
        if (attempts >= maxAttempts) {
          document.getElementById('restart-status').textContent = 'Server did not respond. Try refreshing manually.';
          return;
        }
        setTimeout(poll, 1000);
      }
    }, 2000);
  }

  var desktopRestartBtn = document.getElementById('desktop-restart-btn');
  if (desktopRestartBtn) desktopRestartBtn.addEventListener('click', showRestartModal);

  var mobileRestartBtn = document.getElementById('mobile-restart-btn');
  if (mobileRestartBtn) mobileRestartBtn.addEventListener('click', showRestartModal);

  document.getElementById('restart-backdrop').addEventListener('click', hideRestartModal);
  document.getElementById('restart-cancel-btn').addEventListener('click', hideRestartModal);
  document.getElementById('restart-confirm-btn').addEventListener('click', doRestart);

  // ── HTMX Error Handling ──
  document.body.addEventListener('htmx:responseError', function(e) {
    if (typeof showToast === 'function') {
      showToast('Request failed: ' + (e.detail.xhr.statusText || 'Network error'), 'error');
    }
  });
  document.body.addEventListener('htmx:sendError', function() {
    document.getElementById('conn-banner').classList.remove('hidden');
  });
  document.body.addEventListener('htmx:afterRequest', function(e) {
    if (!e.detail.failed) document.getElementById('conn-banner').classList.add('hidden');
  });
})();
