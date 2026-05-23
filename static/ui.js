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

  function setupNavDrawer() {
    const toggle = document.getElementById('nav-toggle');
    const drawer = document.getElementById('app-nav-drawer');
    if (!toggle || !drawer) return;

    function close() {
      drawer.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', 'Open menu');
    }

    function open() {
      drawer.hidden = false;
      toggle.setAttribute('aria-expanded', 'true');
      toggle.setAttribute('aria-label', 'Close menu');
    }

    toggle.addEventListener('click', function (e) {
      e.stopPropagation();
      drawer.hidden ? open() : close();
    });

    // Close when a link is tapped (so nav doesn't sit open after navigation)
    drawer.addEventListener('click', function (e) {
      if (e.target.closest('a')) close();
    });

    // Close on outside click / Escape
    document.addEventListener('click', function (e) {
      if (drawer.hidden) return;
      if (drawer.contains(e.target) || toggle.contains(e.target)) return;
      close();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !drawer.hidden) close();
    });

    // Auto-close if the viewport grows back into the desktop layout
    const mq = window.matchMedia('(min-width: 768px)');
    function onChange() { if (mq.matches) close(); }
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else mq.addListener(onChange);
  }

  function setupAdNameToggles() {
    document.querySelectorAll('.ad-name-toggle').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        // Row has its own onclick that navigates — don't let it fire.
        e.stopPropagation();
        e.preventDefault();
        const container = btn.closest('.ad-name');
        if (!container) return;
        const textEl = container.querySelector('.ad-name-text');
        const expanded = btn.getAttribute('aria-expanded') === 'true';
        if (expanded) {
          textEl.textContent = container.dataset.short;
          btn.setAttribute('aria-expanded', 'false');
          btn.setAttribute('aria-label', 'Show full name');
          btn.textContent = '…';
        } else {
          textEl.textContent = container.dataset.full;
          btn.setAttribute('aria-expanded', 'true');
          btn.setAttribute('aria-label', 'Collapse name');
          btn.textContent = '(less)';
        }
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    setupTooltips();
    setupToasts();
    setupNavDrawer();
    setupAdNameToggles();
  });
})();
