(function() {
  function autoDetectKeys() {
    var btn = document.getElementById('setup-btn');
    var status = document.getElementById('setup-status');
    btn.disabled = true;
    btn.textContent = 'Detecting...';
    status.classList.remove('hidden');
    status.textContent = 'SSHing to Media Center...';

    fetch('/downloads/setup', { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.success) {
          status.textContent = 'Keys detected! Refreshing...';
          document.getElementById('setup-banner').classList.add('hidden');
          htmx.trigger('#downloads-container', 'refresh');
        } else {
          var errs = data.errors ? data.errors.join('; ') : (data.error || 'Unknown error');
          status.textContent = 'Partial: ' + errs;
          htmx.trigger('#downloads-container', 'refresh');
        }
        btn.disabled = false;
        btn.textContent = 'Auto-detect API Keys';
      })
      .catch(function(err) {
        status.textContent = 'Error: ' + err;
        btn.disabled = false;
        btn.textContent = 'Auto-detect API Keys';
      });
  }

  // Refresh button
  document.getElementById('refresh-btn').addEventListener('click', function() {
    htmx.trigger('#downloads-container', 'refresh');
  });

  // Setup button
  var setupBtn = document.getElementById('setup-btn');
  if (setupBtn) {
    setupBtn.addEventListener('click', autoDetectKeys);
  }

  // Show setup banner if keys are missing
  document.getElementById('downloads-container').addEventListener('htmx:afterSwap', function() {
    if (this.querySelector('[data-needs-setup]')) {
      document.getElementById('setup-banner').classList.remove('hidden');
    } else {
      document.getElementById('setup-banner').classList.add('hidden');
    }
  });
})();
