(function () {
  const STORAGE_KEY = 'display_currency';
  const currencies = window.DISPLAY_CURRENCIES || { USD: { symbol: '$', rate_from_usd: 1 } };
  const fallback = window.DEFAULT_DISPLAY_CURRENCY || 'USD';

  function getDisplayCurrency() {
    let code;
    try { code = localStorage.getItem(STORAGE_KEY); } catch (e) { code = null; }
    return currencies[code] ? code : fallback;
  }

  function formatMoney(usdAmount, code, decimals) {
    const meta = currencies[code] || currencies[fallback];
    const value = (parseFloat(usdAmount) || 0) * meta.rate_from_usd;
    return meta.symbol + value.toLocaleString('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }

  function applyDisplayCurrency() {
    const code = getDisplayCurrency();
    document.querySelectorAll('.money').forEach(function (el) {
      const usd = el.dataset.usd;
      const decimals = parseInt(el.dataset.decimals || '2', 10);
      el.textContent = formatMoney(usd, code, decimals);
    });
    document.querySelectorAll('.currency-toggle').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.dataset.currency === code);
      btn.setAttribute('aria-pressed', btn.dataset.currency === code ? 'true' : 'false');
    });
    document.dispatchEvent(new CustomEvent('display-currency-changed', {
      detail: { code: code, meta: currencies[code] },
    }));
  }

  window.getDisplayCurrency = getDisplayCurrency;
  window.formatMoney = formatMoney;
  window.applyDisplayCurrency = applyDisplayCurrency;

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.currency-toggle').forEach(function (btn) {
      btn.addEventListener('click', function () {
        try { localStorage.setItem(STORAGE_KEY, btn.dataset.currency); } catch (e) {}
        applyDisplayCurrency();
      });
    });
    applyDisplayCurrency();
  });
})();
