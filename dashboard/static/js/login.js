(function() {
  if (localStorage.getItem('theme') === 'light') {
    document.documentElement.classList.remove('dark');
    document.documentElement.classList.add('light');
  }
  document.getElementById('host-info').textContent = window.location.host;
})();
