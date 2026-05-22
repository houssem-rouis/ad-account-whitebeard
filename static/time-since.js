(function () {
  function formatTimeSince(iso) {
    if (!iso) return '';
    const hasTz = iso.endsWith('Z') || /[+\-]\d{2}:?\d{2}$/.test(iso);
    const date = new Date(hasTz ? iso : iso + 'Z');
    if (isNaN(date.getTime())) return iso;
    const seconds = Math.round((Date.now() - date.getTime()) / 1000);
    if (seconds < 5) return 'just now';
    if (seconds < 60) return seconds + ' seconds ago';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes + ' minute' + (minutes === 1 ? '' : 's') + ' ago';
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return hours + ' hour' + (hours === 1 ? '' : 's') + ' ago';
    const days = Math.floor(hours / 24);
    if (days < 30) return days + ' day' + (days === 1 ? '' : 's') + ' ago';
    const months = Math.floor(days / 30);
    if (months < 12) return months + ' month' + (months === 1 ? '' : 's') + ' ago';
    const years = Math.floor(days / 365);
    return years + ' year' + (years === 1 ? '' : 's') + ' ago';
  }

  function refreshTimeSince() {
    document.querySelectorAll('.time-since').forEach(function (el) {
      const iso = el.dataset.iso;
      if (!iso) return;
      el.textContent = formatTimeSince(iso);
      if (!el.title) el.title = iso;
    });
  }

  window.formatTimeSince = formatTimeSince;
  window.refreshTimeSince = refreshTimeSince;

  document.addEventListener('DOMContentLoaded', function () {
    refreshTimeSince();
    setInterval(refreshTimeSince, 30000);
  });
})();
