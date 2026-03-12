(function() {
  if (localStorage.getItem('theme') === 'light') {
    document.documentElement.classList.remove('dark');
    document.documentElement.classList.add('light');
  }
  document.getElementById('host-info').textContent = window.location.host;

  document.getElementById('setup-form').addEventListener('submit', function(e) {
    var pin = document.getElementById('pin').value;
    var confirm = document.getElementById('confirm_pin').value;
    if (!pin) {
      e.preventDefault();
      alert('PIN is required');
      return;
    }
    if (pin !== confirm) {
      e.preventDefault();
      alert('PINs do not match');
    }
  });
})();
