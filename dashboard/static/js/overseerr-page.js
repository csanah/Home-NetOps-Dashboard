(function() {
  // Refresh button
  document.getElementById('refresh-btn').addEventListener('click', function() {
    htmx.trigger('#overseerr-container', 'refresh');
  });

  // Error handler (replacing hx-on::response-error attribute)
  document.getElementById('overseerr-container').addEventListener('htmx:responseError', function() {
    this.innerHTML = '<div class="p-4 text-sm text-red-400">Failed to load Overseerr data. Check server logs.</div>';
  });
})();
