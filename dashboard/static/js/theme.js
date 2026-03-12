// Dark/light theme toggle with localStorage persistence
(function() {
  const html = document.documentElement;
  const saved = localStorage.getItem('theme');

  if (saved === 'light') {
    html.classList.remove('dark');
  } else {
    html.classList.add('dark');
  }

  document.getElementById('theme-toggle').addEventListener('click', function() {
    html.classList.toggle('dark');
    localStorage.setItem('theme', html.classList.contains('dark') ? 'dark' : 'light');
  });
})();
