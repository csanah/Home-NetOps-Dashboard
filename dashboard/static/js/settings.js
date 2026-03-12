(function() {
  function toggleCheckbox(btn) {
    var checked = btn.getAttribute('data-checked') === 'true';
    var newVal = !checked;
    btn.setAttribute('data-checked', newVal ? 'true' : 'false');
    var knob = btn.querySelector('span');
    if (newVal) {
      btn.classList.remove('bg-gray-300', 'dark:bg-gray-600');
      btn.classList.add('bg-blue-600');
      knob.classList.remove('translate-x-1');
      knob.classList.add('translate-x-6');
    } else {
      btn.classList.remove('bg-blue-600');
      btn.classList.add('bg-gray-300', 'dark:bg-gray-600');
      knob.classList.remove('translate-x-6');
      knob.classList.add('translate-x-1');
    }
  }

  function saveSection(section) {
    var form = document.getElementById('form-' + section);
    var status = document.getElementById('status-' + section);
    var data = {};
    form.querySelectorAll('input[name]').forEach(function(input) {
      data[input.name] = input.value;
    });
    form.querySelectorAll('[data-name][data-checked]').forEach(function(btn) {
      data[btn.getAttribute('data-name')] = btn.getAttribute('data-checked');
    });

    status.textContent = 'Saving...';
    status.className = 'text-sm text-gray-500';

    fetch('/settings/save/' + section, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    .then(function(r) { return r.json(); })
    .then(function(result) {
      if (result.success) {
        if (result.restart_required) {
          var portInput = form.querySelector('[name="DASHBOARD_PORT"]');
          var newPort = portInput ? portInput.value.trim() : '';
          if (newPort && newPort !== window.location.port) {
            window.location.href = '/restarting?port=' + encodeURIComponent(newPort) + '&next=/settings';
            return;
          }
          showToast('Saved! Restart required for port change.', 'warning');
        } else {
          showToast('Settings saved.', 'success');
        }
      } else {
        showToast(result.error || 'Save failed', 'error');
      }
    })
    .catch(function(err) {
      showToast('Error: ' + err.message, 'error');
    });
  }

  function testConnection(section, testType, btn) {
    var status = document.getElementById('status-' + section);
    var origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Testing...';

    var system = '';
    if (testType === 'api' || testType === 'ssh') {
      system = section + '_' + testType;
    } else {
      system = testType;
    }

    fetch('/settings/test/' + system, { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(result) {
      btn.disabled = false;
      btn.textContent = origText;
      showToast(result.message, result.success ? 'success' : 'error');
    })
    .catch(function(err) {
      btn.disabled = false;
      btn.textContent = origText;
      showToast('Error: ' + err.message, 'error');
    });
  }

  function autoDetectKeys(btn, sectionId) {
    sectionId = sectionId || 'media_services';
    var origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Detecting...';

    var url = sectionId === 'plex' ? '/plex/auto-detect' : sectionId === 'overseerr' ? '/overseerr/auto-detect' : '/settings/auto-detect-keys';

    fetch(url, { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(result) {
      btn.disabled = false;
      btn.textContent = origText;
      if (sectionId === 'plex' || sectionId === 'overseerr') {
        if (result.success) {
          showToast(result.message || (sectionId === 'plex' ? 'Token detected and saved!' : 'API key detected and saved!'), 'success');
          setTimeout(function() { location.reload(); }, 1500);
        } else {
          showToast(result.error || 'Detection failed', 'warning');
        }
      } else {
        if (result.keys) {
          var fields = { sabnzbd: 'SABNZBD_API_KEY', sonarr: 'SONARR_API_KEY', prowlarr: 'PROWLARR_API_KEY', radarr: 'RADARR_API_KEY' };
          for (var key in fields) {
            if (result.keys[key]) {
              var el = document.getElementById('field-' + fields[key]);
              if (el) el.value = result.keys[key];
            }
          }
        }
        if (result.success) {
          showToast('Keys detected and saved!', 'success');
        } else {
          var errMsg = (result.errors || []).join('; ') || result.error || 'Detection failed';
          showToast(errMsg, 'warning');
        }
      }
    })
    .catch(function(err) {
      btn.disabled = false;
      btn.textContent = origText;
      showToast('Error: ' + err.message, 'error');
    });
  }

  function togglePassword(btn) {
    var input = btn.parentElement.querySelector('input');
    var showIcon = btn.querySelector('.eye-show');
    var hideIcon = btn.querySelector('.eye-hide');
    if (input.type === 'password') {
      input.type = 'text';
      showIcon.classList.add('hidden');
      hideIcon.classList.remove('hidden');
    } else {
      input.type = 'password';
      showIcon.classList.remove('hidden');
      hideIcon.classList.add('hidden');
    }
  }

  // ── Settings tab navigation ──
  var TAB_SECTIONS = {
    general:  ['layout', 'claude_chat', 'dashboard', 'backup'],
    systems:  ['udm', 'proxmox', 'ha', 'nas', 'bike', 'media'],
    services: ['plex', 'overseerr', 'media_services'],
  };

  function switchSettingsTab(tab) {
    document.querySelectorAll('.settings-tab-btn').forEach(function(btn) {
      var isActive = btn.dataset.tab === tab;
      btn.classList.toggle('bg-white', isActive);
      btn.classList.toggle('dark:bg-gray-600', isActive);
      btn.classList.toggle('text-gray-900', isActive);
      btn.classList.toggle('dark:text-white', isActive);
      btn.classList.toggle('shadow-sm', isActive);
      btn.classList.toggle('text-gray-600', !isActive);
      btn.classList.toggle('dark:text-gray-300', !isActive);
    });
    var active = TAB_SECTIONS[tab] || [];
    var allSections = [];
    for (var k in TAB_SECTIONS) allSections = allSections.concat(TAB_SECTIONS[k]);
    allSections.forEach(function(id) {
      var el = document.getElementById('section-' + id);
      if (el) el.classList.toggle('hidden', active.indexOf(id) === -1);
    });
    history.replaceState(null, '', '#' + tab);
  }

  // ── Event delegation ──
  document.addEventListener('click', function(e) {
    var el;
    if ((el = e.target.closest('.checkbox-toggle'))) {
      toggleCheckbox(el);
    } else if ((el = e.target.closest('.toggle-password-btn'))) {
      togglePassword(el);
    } else if ((el = e.target.closest('.test-connection-btn'))) {
      testConnection(el.dataset.section, el.dataset.test, el);
    } else if ((el = e.target.closest('.auto-detect-btn'))) {
      autoDetectKeys(el, el.dataset.section);
    } else if ((el = e.target.closest('.save-section-btn'))) {
      saveSection(el.dataset.section);
    } else if ((el = e.target.closest('.settings-tab-btn'))) {
      switchSettingsTab(el.dataset.tab);
    }
  });

  // Prevent default form submission
  document.querySelectorAll('form[id^="form-"]').forEach(function(f) {
    f.addEventListener('submit', function(e) { e.preventDefault(); });
  });

  // Init from URL hash
  var validTabs = Object.keys(TAB_SECTIONS);
  var hash = location.hash.replace('#', '');
  switchSettingsTab(validTabs.indexOf(hash) !== -1 ? hash : 'general');
})();
