// ── Firewall Rules ──
let rulesLoaded = false;

function refreshRules() {
  const tbody = document.getElementById('rules-tbody');
  tbody.innerHTML = '<tr><td colspan="6" class="px-4 py-8 text-center text-gray-400">Loading rules...</td></tr>';

  fetch('/firewall/rules')
    .then(r => r.json())
    .then(rules => {
      rulesLoaded = true;
      if (!rules.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="px-4 py-8 text-center text-gray-400">No firewall rules found</td></tr>';
        return;
      }
      let html = '';
      rules.forEach(rule => {
        const actionColor = {
          allow: 'bg-green-500/20 text-green-600 dark:text-green-400',
          accept: 'bg-green-500/20 text-green-600 dark:text-green-400',
          block: 'bg-red-500/20 text-red-600 dark:text-red-400',
          drop: 'bg-red-500/20 text-red-600 dark:text-red-400',
          reject: 'bg-orange-500/20 text-orange-600 dark:text-orange-400'
        }[rule.action?.toLowerCase()] || 'bg-gray-500/20 text-gray-500';

        const enabledDot = rule.enabled
          ? '<span class="inline-block w-2.5 h-2.5 rounded-full bg-green-500"></span>'
          : '<span class="inline-block w-2.5 h-2.5 rounded-full bg-gray-400"></span>';

        html += `<tr class="hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors">
          <td class="px-4 py-3 font-medium">${escapeHtml(rule.name || '-')}</td>
          <td class="px-4 py-3"><span class="px-2 py-0.5 rounded text-xs font-bold uppercase ${actionColor}">${escapeHtml(rule.action || '-')}</span></td>
          <td class="px-4 py-3 text-gray-500 dark:text-gray-400">${escapeHtml(rule.source_zone || '-')}</td>
          <td class="px-4 py-3 text-gray-500 dark:text-gray-400">${escapeHtml(rule.dest_zone || '-')}</td>
          <td class="px-4 py-3 text-gray-500 dark:text-gray-400">${escapeHtml(rule.protocol || 'Any')}</td>
          <td class="px-4 py-3 text-center">${enabledDot}</td>
        </tr>`;
      });
      tbody.innerHTML = html;
    })
    .catch(err => {
      tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-red-400">Failed to load rules: ${escapeHtml(err.message)}</td></tr>`;
    });
}
