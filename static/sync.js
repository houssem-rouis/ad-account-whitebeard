(function () {
  function showLoader() {
    const overlay = document.getElementById('sync-loader-overlay');
    if (overlay) overlay.classList.remove('d-none');
  }

  function hideLoader() {
    const overlay = document.getElementById('sync-loader-overlay');
    if (overlay) overlay.classList.add('d-none');
  }

  async function syncAds(url, options) {
    options = options || {};
    if (!url) return;
    showLoader();
    try {
      const separator = url.includes('?') ? '&' : '?';
      const fetchUrl = url + separator + 'ajax=1' + (options.auto ? '&auto=1' : '');
      const response = await fetch(fetchUrl, { credentials: 'same-origin' });
      const data = await response.json();
      if (response.ok && data.success) {
        if (options.reloadOnSuccess !== false) {
          window.location.reload();
        }
      } else {
        console.error('Sync failed', data);
        if (options.notifyOnError !== false) {
          alert(data.message || 'Sync failed.');
        }
      }
    } catch (error) {
      console.error(error);
      if (options.notifyOnError !== false) {
        alert('Unable to sync ads at this time.');
      }
    } finally {
      hideLoader();
    }
  }

  window.syncAds = syncAds;

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-sync-url]').forEach(function (button) {
      button.addEventListener('click', function (event) {
        event.preventDefault();
        syncAds(button.dataset.syncUrl, { auto: false, notifyOnError: true });
      });
    });

    document.querySelectorAll('[data-auto-sync="true"]').forEach(function (el) {
      syncAds(el.dataset.syncUrl, { auto: true, notifyOnError: false });
    });
  });
})();
