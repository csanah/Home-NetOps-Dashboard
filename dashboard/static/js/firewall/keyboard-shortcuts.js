// ── Keyboard Shortcuts ──
function toggleShortcutHelp() {
  const overlay = document.getElementById('shortcut-help');
  if (overlay) overlay.classList.toggle('hidden');
}

document.addEventListener('keydown', function(e) {
  // Skip when focus is in an input/textarea
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

  switch (e.key) {
    case 's': case 'S': startStream(); break;
    case 'x': case 'X': stopStream(); break;
    case 'p': case 'P': togglePause(); break;
    case 'c': case 'C': clearLogs(); break;
    case '1': switchTab('logs'); break;
    case '2': switchTab('lookup'); break;
    case '3': switchTab('rules'); break;
    case '?': toggleShortcutHelp(); break;
    case 'Escape':
      hideIpPopover();
      hideServerMenu();
      const help = document.getElementById('shortcut-help');
      if (help && !help.classList.contains('hidden')) help.classList.add('hidden');
      break;
  }
});
