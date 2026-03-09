// Toast notification system
(function() {
  // Create container on load
  const container = document.createElement('div');
  container.id = 'toast-container';
  container.style.cssText = 'position:fixed;bottom:1.5rem;right:1.5rem;z-index:9999;display:flex;flex-direction:column-reverse;gap:0.5rem;pointer-events:none;';
  document.body.appendChild(container);

  const icons = {
    success: '<svg class="w-4 h-4 text-green-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>',
    error:   '<svg class="w-4 h-4 text-red-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>',
    warning: '<svg class="w-4 h-4 text-amber-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>',
    info:    '<svg class="w-4 h-4 text-blue-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>'
  };

  window.showToast = function(message, type) {
    type = type || 'info';
    const toast = document.createElement('div');
    toast.className = 'toast-item';
    toast.style.cssText = 'pointer-events:auto;display:flex;align-items:center;gap:0.5rem;padding:0.75rem 1rem;border-radius:0.75rem;font-size:0.8125rem;max-width:22rem;box-shadow:0 4px 12px rgba(0,0,0,0.3);animation:toast-in 0.3s ease forwards;'
      + 'background:#1f2937;color:#e5e7eb;border:1px solid #374151;';

    toast.innerHTML = (icons[type] || icons.info)
      + '<span style="flex:1">' + message + '</span>'
      + '<button onclick="this.parentElement.remove()" style="color:#6b7280;cursor:pointer;padding:2px;" aria-label="Dismiss">'
      + '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>'
      + '</button>';

    container.appendChild(toast);

    setTimeout(function() {
      toast.style.animation = 'toast-out 0.3s ease forwards';
      setTimeout(function() { toast.remove(); }, 300);
    }, 4000);
  };
})();
