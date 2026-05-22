(function () {
  function setupTooltips() {
    if (!window.bootstrap || !bootstrap.Tooltip) return;
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
      new bootstrap.Tooltip(el);
    });
  }

  function dismissToast(el) {
    if (!el) return;
    el.style.opacity = '0';
    el.style.transform = 'translateY(-6px)';
    el.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
    setTimeout(function () { el.remove(); }, 220);
  }

  function setupToasts() {
    document.querySelectorAll('.toast-flash').forEach(function (toast) {
      const closeBtn = toast.querySelector('.toast-close');
      if (closeBtn) closeBtn.addEventListener('click', function () { dismissToast(toast); });
      const ttl = parseInt(toast.dataset.autohide || '0', 10);
      if (ttl > 0) setTimeout(function () { dismissToast(toast); }, ttl);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    setupTooltips();
    setupToasts();
  });
})();
