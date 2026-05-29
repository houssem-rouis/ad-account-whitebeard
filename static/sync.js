(function () {
  // A mix of light-hearted status lines and real copywriting wisdom so the
  // wait never feels boring. Lines with an `author` render as a quote.
  // Optional `image` is a path under /static/ (e.g. 'quotes/ogilvy.jpg').
  // Drop the file into static/ and it shows automatically; if the file is
  // missing the image just hides itself — no broken-image icon.
  const QUIPS = [
    { text: 'Bribing the algorithm with cookies… 🍪', image: 'quotes/cookie.png' },
    { text: 'Teaching the robots to sell dog treats. 🐾', image: 'quotes/dog.png' },
    { text: 'Asking Meta nicely for the numbers.' },
    { text: 'Counting pixels, one impression at a time.' },
    { text: 'Herding your ad data into one place.' },
    { text: 'Polishing the conversions until they shine.' },
    { text: 'Convincing the spreadsheet to behave.' },
    { text: 'Untangling the attribution spaghetti. 🍝', image: 'quotes/spaghetti.png' },
    { text: 'Almost there — the data is putting its shoes on.' },
    { text: 'Reticulating splines… just kidding, fetching ads.' },
    { text: 'On the average, five times as many people read the headline as read the body copy.', author: 'David Ogilvy', image: 'quotes/ogilvy.jpg' },
    { text: 'The consumer isn’t a moron; she is your wife.', author: 'David Ogilvy', image: 'quotes/ogilvy.jpg' },
    { text: 'If it doesn’t sell, it isn’t creative.', author: 'David Ogilvy', image: 'quotes/ogilvy.jpg' },
    { text: 'Tell the truth, but make the truth fascinating.', author: 'David Ogilvy', image: 'quotes/ogilvy.jpg' },
    { text: 'Make it simple. Make it memorable. Make it inviting to look at.', author: 'Leo Burnett', image: 'quotes/burnett.jpg' },
    { text: 'Don’t tell me how good you make it; tell me how good it makes me when I use it.', author: 'Leo Burnett', image: 'quotes/burnett.jpg' },
    { text: 'People don’t read ads. They read what interests them. Sometimes it’s an ad.', author: 'Howard Gossage', image: 'quotes/gossage.jpg' },
    { text: 'Either write something worth reading or do something worth writing.', author: 'Benjamin Franklin', image: 'quotes/franklin.jpg' },
    { text: 'The more informative your advertising, the more persuasive it will be.', author: 'David Ogilvy', image: 'quotes/ogilvy.jpg' },
    { text: 'Good copy can’t be written with tongue in cheek. You’ve got to believe in the product.', author: 'David Ogilvy', image: 'quotes/ogilvy.jpg' },
    { text: 'When you have written your headline, you have spent eighty cents out of your dollar.', author: 'David Ogilvy', image: 'quotes/ogilvy.jpg' },
    { text: 'The headline is the ticket on the meat. Use it to flag down readers who are prospects.', author: 'David Ogilvy', image: 'quotes/ogilvy.jpg' },
    { text: 'Never write an advertisement you wouldn’t want your own family to read.', author: 'David Ogilvy', image: 'quotes/ogilvy.jpg' },
    { text: 'Don’t count the people you reach; reach the people that count.', author: 'David Ogilvy', image: 'quotes/ogilvy.jpg' },
    { text: 'Make the customer the hero of your story.', author: 'Ann Handley', image: 'quotes/handley.jpg' },
    { text: 'Good content isn’t about good storytelling. It’s about telling a true story well.', author: 'Ann Handley', image: 'quotes/handley.jpg' },
    { text: 'The best advertising is word-of-mouth advertising — but you have to earn it.', author: 'Bob Bly', image: 'quotes/bly.jpg' },
    { text: 'You cannot bore people into buying your product; you can only interest them in buying it.', author: 'David Ogilvy', image: 'quotes/ogilvy.jpg' },
    { text: 'Copy is a direct conversation with the consumer.', author: 'Shirley Polykoff', image: 'quotes/polykoff.jpg' },
    { text: 'Advertising is salesmanship in print.', author: 'John E. Kennedy', image: 'quotes/kennedy.jpg' },
    { text: 'The most powerful element in advertising is the truth.', author: 'Bill Bernbach', image: 'quotes/bernbach.jpg' },
    { text: 'Rules are what the artist breaks; the memorable never emerged from a formula.', author: 'Bill Bernbach', image: 'quotes/bernbach.jpg' },
    { text: 'In writing, you must kill all your darlings.', author: 'William Faulkner', image: 'quotes/faulkner.jpg' },
    { text: 'The reader doesn’t turn the page because of the writing; he turns the page in spite of it.', author: 'Eugene Schwartz', image: 'quotes/schwartz.jpg' },
    { text: 'Copy is not written. Copy is assembled.', author: 'Eugene Schwartz', image: 'quotes/schwartz.jpg' },
    { text: 'I notice that you use plain, simple language, short words and brief sentences. That is the way to write English.', author: 'Mark Twain', image: 'quotes/twain.jpg' },
    { text: 'The difference between the almost right word and the right word is the difference between the lightning bug and the lightning.', author: 'Mark Twain', image: 'quotes/twain.jpg' },
    { text: 'Sell the sizzle, not the steak.', author: 'Elmer Wheeler', image: 'quotes/wheeler.jpg' },
    { text: 'A good ad should be like a good sermon: it must not only comfort the afflicted — it must also afflict the comfortable.', author: 'Bernice Fitz-Gibbon', image: 'quotes/fitzgibbon.jpg' },
    { text: 'Write to be understood, speak to be heard, read to grow.', author: 'Lawrence Clark Powell', image: 'quotes/powell.jpg' },
  ];

  // Where per-quip images live (Flask serves the static folder at /static/).
  const STATIC_BASE = '/static/';

  let quoteTimer = null;
  let lastQuipIndex = -1;

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function pickQuip() {
    if (QUIPS.length <= 1) return 0;
    let index;
    do {
      index = Math.floor(Math.random() * QUIPS.length);
    } while (index === lastQuipIndex);
    lastQuipIndex = index;
    return index;
  }

  function renderQuote(el) {
    const quip = QUIPS[pickQuip()];
    let text = escapeHtml(quip.text);
    if (quip.author) {
      text = '“' + text + '”<span class="sync-loader-quote-author">— ' +
        escapeHtml(quip.author) + '</span>';
    }
    // Hide the <img> if the file is missing so it never shows a broken icon.
    const img = quip.image
      ? '<img class="sync-loader-quote-img" src="' + escapeHtml(STATIC_BASE + quip.image) +
        '" alt="" onerror="this.remove()">'
      : '';
    const html = img + '<div class="sync-loader-quote-text">' + text + '</div>';
    el.classList.toggle('has-image', Boolean(quip.image));
    el.classList.remove('is-visible');
    // Fade out, swap, fade back in.
    window.setTimeout(function () {
      el.innerHTML = html;
      el.classList.add('is-visible');
    }, 350);
  }

  function startQuotes() {
    const el = document.getElementById('sync-loader-quote');
    if (!el) return;
    renderQuote(el);
    if (quoteTimer) window.clearTimeout(quoteTimer);
    // Rotate every 10–20s, re-randomised each tick so it feels alive.
    const tick = function () {
      renderQuote(el);
      quoteTimer = window.setTimeout(tick, 10000 + Math.random() * 10000);
    };
    quoteTimer = window.setTimeout(tick, 10000 + Math.random() * 10000);
  }

  function stopQuotes() {
    if (quoteTimer) {
      window.clearTimeout(quoteTimer);
      quoteTimer = null;
    }
    const el = document.getElementById('sync-loader-quote');
    if (el) el.classList.remove('is-visible');
  }

  function showLoader() {
    const overlay = document.getElementById('sync-loader-overlay');
    if (overlay) overlay.classList.remove('d-none');
    startQuotes();
  }

  function hideLoader() {
    const overlay = document.getElementById('sync-loader-overlay');
    if (overlay) overlay.classList.add('d-none');
    stopQuotes();
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
