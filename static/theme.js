(function () {
  const root = document.documentElement;
  const STORAGE_KEY = 'theme';

  function currentTheme() {
    return root.getAttribute('data-theme') || 'light';
  }

  function setTheme(value) {
    root.setAttribute('data-theme', value);
    try { localStorage.setItem(STORAGE_KEY, value); } catch (e) {}
    syncIcons();
  }

  function syncIcons() {
    const isDark = currentTheme() === 'dark';
    const sun = document.getElementById('theme-icon-sun');
    const moon = document.getElementById('theme-icon-moon');
    if (sun) sun.style.display = isDark ? 'none' : '';
    if (moon) moon.style.display = isDark ? '' : 'none';
  }

  document.addEventListener('DOMContentLoaded', function () {
    syncIcons();
    const toggle = document.getElementById('theme-toggle');
    if (!toggle) return;
    toggle.addEventListener('click', function () {
      setTheme(currentTheme() === 'light' ? 'dark' : 'light');
    });
  });
})();
