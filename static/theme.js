const toggle = document.getElementById('theme-toggle');
const root = document.documentElement;
const initial = localStorage.getItem('theme') || 'light';
root.setAttribute('data-theme', initial);
if (toggle) {
  toggle.addEventListener('click', () => {
    const next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    root.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
  });
}
