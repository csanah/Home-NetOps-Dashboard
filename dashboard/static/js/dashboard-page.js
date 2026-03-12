(function() {
  var configEl = document.getElementById('system-config');
  var systemNames = JSON.parse(configEl.dataset.names);

  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }

  var previousStates = {};

  function readCurrentStates() {
    var states = {};
    document.querySelectorAll('[data-system-key]').forEach(function(el) {
      states[el.dataset.systemKey] = el.dataset.online === 'true';
    });
    return states;
  }

  previousStates = readCurrentStates();

  document.body.addEventListener('htmx:afterSwap', function(e) {
    if (!e.detail.target || e.detail.target.id !== 'cards-container') return;

    var newStates = readCurrentStates();
    if ('Notification' in window && Notification.permission === 'granted') {
      for (var key in newStates) {
        if (previousStates[key] === true && newStates[key] === false) {
          new Notification('System Down', {
            body: (systemNames[key] || key) + ' went offline',
            tag: 'system-down-' + key
          });
        } else if (previousStates[key] === false && newStates[key] === true) {
          new Notification('System Recovered', {
            body: (systemNames[key] || key) + ' is back online',
            tag: 'system-up-' + key
          });
        }
      }
    }
    previousStates = newStates;
  });
})();
