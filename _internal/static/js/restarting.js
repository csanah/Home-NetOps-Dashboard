(function() {
  if (localStorage.getItem('theme') === 'light') {
    document.documentElement.classList.remove('dark');
    document.documentElement.classList.add('light');
  }

  var configEl = document.getElementById('restart-config');
  var newPort = configEl.dataset.port || '';
  var nextUrl = configEl.dataset.nextUrl || '/';
  var statusEl = document.getElementById('status-text');

  var targetOrigin = window.location.protocol + '//' + window.location.hostname;
  if (newPort) {
    targetOrigin += ':' + newPort;
  } else {
    targetOrigin += ':' + window.location.port;
  }
  var targetUrl = targetOrigin + nextUrl;

  fetch('/api/restart', { method: 'POST' }).catch(function() {});

  var attempts = 0;
  var maxAttempts = 30;
  setTimeout(function poll() {
    statusEl.textContent = 'Waiting for server on port ' + (newPort || window.location.port) + '...';
    fetch(targetOrigin + '/api/health', { cache: 'no-store' })
      .then(function(r) {
        if (r.ok) {
          statusEl.textContent = 'Server is back!';
          setTimeout(function() { window.location.href = targetUrl; }, 500);
        } else {
          retry();
        }
      })
      .catch(function() { retry(); });

    function retry() {
      attempts++;
      if (attempts >= maxAttempts) {
        statusEl.textContent = 'Server did not respond. Try navigating to ' + targetUrl + ' manually.';
        return;
      }
      setTimeout(poll, 1000);
    }
  }, 2000);
})();
