(function() {
  // Refresh button
  document.getElementById('refresh-btn').addEventListener('click', function() {
    htmx.trigger('#plex-sessions', 'refresh');
    htmx.trigger('#plex-container', 'refresh');
  });

  // Error handlers (replacing hx-on::response-error attributes)
  document.getElementById('plex-sessions').addEventListener('htmx:responseError', function() {
    this.innerHTML = '<div class="p-4 text-sm text-red-400">Failed to load sessions. Check server logs.</div>';
  });

  document.getElementById('plex-container').addEventListener('htmx:responseError', function() {
    this.innerHTML = '<div class="p-4 text-sm text-red-400">Failed to load Plex data. Check server logs.</div>';
  });
})();
