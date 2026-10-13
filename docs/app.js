/* Dashboard UI. Reads data/*.json committed by the GitHub Action (same origin
 * on GitHub Pages) and keeps paper trades in this browser's localStorage. */
(function () {
  "use strict";
  var PT = window.PaperTrade;
  var STORE_KEY = "trendscanner.paper.v1";
  var $ = function (s, el) { return (el || document).querySelector(s); };
  var data = null; // latest results.json

  // ------------------------------------------------------------ utilities
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function money(n, sign) {
    if (n == null || !isFinite(n)) return "—";
    var s = Math.abs(n).toLocaleString(undefined, { style: "currency", currency: "USD" });
    return (n < 0 ? "-" : sign && n > 0 ? "+" : "") + s;
  }
  function pct(n, sign) {
    if (n == null || !isFinite(n)) return "—";
    return (sign && n > 0 ? "+" : "") + (n * 100).toFixed(1) + "%";
  }
  function cls(n) { return n > 0 ? "pos" : n < 0 ? "neg" : ""; }
  function today() {
    var d = new Date();
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  }
  function ago(iso) {
    var mins = Math.round((Date.now() - Date.parse(iso)) / 60000);
    if (mins < 60) return mins + " min ago";
    if (mins < 48 * 60) return Math.round(mins / 60) + " h ago";
    return Math.round(mins / 1440) + " days ago";
  }
  function fetchJSON(path) {
    return fetch(path + "?t=" + Date.now(), { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(path + ": HTTP " + r.status);
      return r.json();
    });
  }

  // ------------------------------------------------------------ tabs
  function showTab(name) {
    document.querySelectorAll(".tabs button").forEach(function (b) {
      b.setAttribute("aria-selected", String(b.dataset.tab === name));
    });
    ["signals", "movers", "trending", "paper"].forEach(function (t) { $("#tab-" + t).hidden = name !== t; });
    try { localStorage.setItem("trendscanner.tab", name); } catch (e) {}
    window.scrollTo(0, 0);
  }
  document.querySelectorAll(".tabs button").forEach(function (b) {
    b.addEventListener("click", function () { showTab(b.dataset.tab); });
  });

  // ------------------------------------------------------------ signals view
  var ICON = { fired: "✅", ok: "▫️", unavailable: "⚠️", error: "❌", not_implemented: "➖" };
  var LABEL = {
    earnings_drift: "Earnings drift", insider_buying: "Insider buying",
    short_squeeze_setup: "Short-squeeze setup", congressional_trades: "Congress trades",
    social_spike: "Social spike", chart_patterns: "Chart pattern"
  };

  function loadSignals() {
    $("#load-error").hidden = true;
    $("#updated").textContent = "Loading…";
    return fetchJSON("data/results.json").then(function (d) {
      data = d;
      renderSignals();
      renderPaper();
      renderTrending();
      renderMovers();
    }).catch(function (e) {
      $("#updated").textContent = "No scan data yet";
      var el = $("#load-error");
      el.hidden = false;
      el.textContent = "Couldn't load scan results (" + e.message + "). If you just set this up, run the " +
        "\"Scan watchlist\" workflow once from the Actions tab on GitHub.";
      renderPaper();
    });
    // backtest is optional
  }

  function renderSignals() {
    var d = data;
    if (!d.generated_at) {
      $("#updated").textContent = "Waiting for first scan";
      $("#tickers").innerHTML = '<div class="card empty">No scan has run yet. Open your repo on GitHub → ' +
        "Actions → Scan watchlist → Run workflow.</div>";
      renderAbout();
      return;
    }
    $("#updated").textContent = "Updated " + ago(d.generated_at) + " · alert ≥ " + d.alert_threshold;
    var hours = (Date.now() - Date.parse(d.generated_at)) / 3.6e6;
    var stale = $("#stale");
    stale.hidden = hours < 40;
    if (!stale.hidden) stale.textContent = "Last scan was " + ago(d.generated_at) +
      ". It normally runs twice each weekday - check the Actions tab on GitHub if this persists.";

    renderTickerList();
    renderAbout();
  }

  // Filter + search over ~500 scanned stocks; only the first 60 matches are drawn.
  var sigFilter = "top";
  var MAX_CARDS = 60;

  function renderFilters() {
    var all = (data && data.tickers) || [];
    var n = {
      top: all.filter(function (t) { return t.tier || t.on_watchlist || t.source === "trending"; }).length,
      alert: all.filter(function (t) { return t.tier === "alert"; }).length,
      watch: all.filter(function (t) { return t.tier === "watch"; }).length,
      watchlist: all.filter(function (t) { return t.on_watchlist; }).length,
      all: all.length
    };
    var labels = { top: "Highlights", alert: "🔔 Alerts", watch: "👀 Watch", watchlist: "⭐ My list", all: "All" };
    $("#sig-filters").innerHTML = Object.keys(labels).map(function (k) {
      return '<button type="button" data-f="' + k + '" aria-selected="' + (k === sigFilter) + '">' + labels[k] +
        " <small>" + n[k] + "</small></button>";
    }).join("");
    $("#sig-count").textContent = (data.scanned || all.length) + " stocks scanned · alert ≥ " + data.alert_threshold +
      (data.watch_threshold != null ? " · watch ≥ " + data.watch_threshold : "");
  }

  function renderTickerList() {
    var d = data;
    renderFilters();
    var q = ($("#sig-search").value || "").trim().toLowerCase();
    var list = (d.tickers || []).filter(function (t) {
      if (q) return t.ticker.toLowerCase().indexOf(q) === 0 || (t.keyword || "").toLowerCase().indexOf(q) >= 0;
      if (sigFilter === "alert") return t.tier === "alert";
      if (sigFilter === "watch") return t.tier === "watch";
      if (sigFilter === "watchlist") return t.on_watchlist;
      if (sigFilter === "top") return t.tier || t.on_watchlist || t.source === "trending";
      return true;
    });
    var extra = list.length > MAX_CARDS ? '<p class="muted small">Showing the top ' + MAX_CARDS + " of " + list.length +
      " by score - search to find any stock.</p>" : "";
    var thr = d.alert_threshold;
    $("#tickers").innerHTML = list.slice(0, MAX_CARDS).map(function (t) {
      var fired = t.signals.filter(function (s) { return s.triggered; });
      var rows = t.signals.map(function (s) {
        var state = s.triggered ? "fired" : s.status;
        var pts = s.triggered ? "+" + s.score_contribution.toFixed(2) : s.status === "ok" ? "0" : s.status;
        return '<div class="sig"><span class="ic" title="' + esc(state) + '">' + (ICON[state] || "•") + "</span>" +
          '<span class="nm">' + esc(LABEL[s.name] || s.name) + '<span class="chip">' + esc(s.evidence) +
          " evidence</span></span>" +
          '<span class="pts' + (s.triggered ? " on" : "") + '">' + esc(pts) + "</span>" +
          '<span class="dt">' + esc(s.detail) +
          (s.triggered ? " <em>(strength " + s.strength.toFixed(2) + " × weight " + s.weight + ")</em>" : "") +
          "</span></div>";
      }).join("");
      var raw = {};
      t.signals.forEach(function (s) { raw[s.name] = s.raw; });
      return '<details class="card tcard">' +
        "<summary>" +
        '<div class="thead"><span class="sym">' + esc(t.ticker) + '</span><span class="kw">' + esc(t.keyword) +
        "</span>" + (t.source === "trending" ? '<span class="badge src">from Trending</span>' : "") +
        (t.on_watchlist ? '<span class="badge src">⭐</span>' : "") +
        (formingOf(t) ? '<span class="badge src" title="chart pattern forming">📐 forming</span>' : "") +
        (t.alert ? '<span class="badge">ALERT</span>' : t.tier === "watch" ? '<span class="badge building">WATCH</span>' : "") +
        '<span class="score">' + t.score.toFixed(1) + "</span></div>" +
        '<div class="bar' + (t.alert ? " hot" : "") + '" role="img" aria-label="Score ' + t.score + ' of 10">' +
        '<i style="width:' + Math.max(0, Math.min(100, t.score * 10)) + '%"></i>' +
        '<b style="left:calc(' + thr * 10 + '% - 1px)" title="alert threshold"></b></div>' +
        '<div class="fired-line">' + (fired.length ? "Fired: " + fired.map(function (s) {
          return esc(LABEL[s.name] || s.name);
        }).join(", ") : "No signals fired") +
        (t.last_close ? " · last close $" + Number(t.last_close).toFixed(2) : "") +
        (t.sector ? " · " + esc(t.sector) : "") + "</div>" +
        "</summary>" +
        '<div class="tbody">' + rows +
        '<p class="math">' + esc(t.math || (t.explanation || []).slice(-1)[0] || "") + "</p>" +
        '<button type="button" class="link" data-trade="' + esc(t.ticker) + '" data-price="' +
        esc(t.last_close || "") + '" data-reason="' + esc("Score " + t.score.toFixed(1) +
          (fired.length ? ": " + fired.map(function (s) { return LABEL[s.name] || s.name; }).join(" + ") : "")) +
        '">Paper-trade ' + esc(t.ticker) + " →</button>" +
        '<details class="raw"><summary>Raw data (debugging)</summary><pre>' +
        esc(JSON.stringify(raw, null, 1)) + "</pre></details>" +
        "</div></details>";
    }).join("") + extra || '<div class="card empty">' + (q ? "No stock matches \u201c" + esc(q) + "\u201d." :
      sigFilter === "alert" ? "No alerts right now - they need several signals to agree, so they're rare." :
      sigFilter === "watch" ? "Nothing on the watch tier right now." : "Nothing to show.") + "</div>";
  }

  $("#sig-filters").addEventListener("click", function (e) {
    var b = e.target.closest("[data-f]");
    if (!b) return;
    sigFilter = b.dataset.f;
    $("#sig-search").value = "";
    renderTickerList();
  });
  $("#sig-search").addEventListener("input", function () { if (data) renderTickerList(); });

  function formingOf(t) {
    var cp = (t.signals || []).filter(function (s) { return s.name === "chart_patterns"; })[0];
    var f = cp && cp.raw && cp.raw.forming;
    return f && Object.keys(f).length ? f : null;
  }

  function renderAbout() {
    var d = data || {};
    var w = d.weights || {};
    $("#formula").textContent = "Score = (sum of weight × strength for each signal that fired) ÷ " +
      (d.total_weight || "total weight") + " × 10. Signals that couldn't be checked count as 0. " +
      "Alert at " + (d.alert_threshold != null ? d.alert_threshold : "?") + "+. Paper-trade hold period: " +
      (d.hold_days || "?") + " trading days. Change any of this in config.json.";
    $("#weights").innerHTML = Object.keys(w).map(function (k) {
      return "<li>" + esc(LABEL[k] || k) + ": weight " + esc(w[k]) + "</li>";
    }).join("");
    $("#stubs").innerHTML = (d.not_implemented || []).map(function (s) {
      return "<li><b>" + esc(s.name) + "</b> - " + esc(s.detail) + "</li>";
    }).join("");
  }

  function loadTrack() {
    fetchJSON("data/backtest.json").then(function (b) {
      var s = b.summary || {};
      var el = $("#track");
      el.hidden = false;
      if (!s.completed) {
        el.innerHTML = "<h2>Scanner track record</h2><p class=\"muted small\">No completed " + esc(s.hold_days) +
          "-day tests yet" + (s.pending ? " (" + s.pending + " in progress)" : "") +
          ". Each alert is checked " + esc(s.hold_days) + " trading days later against SPY.</p>";
        return;
      }
      el.innerHTML = "<h2>Scanner track record</h2>" +
        '<p class="muted small">Alerts scoring ≥ ' + esc(s.min_score) + ", bought next day, sold after " +
        esc(s.hold_days) + " trading days. " + (s.completed < 30 ? "Tiny sample - treat as anecdote." : "") + "</p>" +
        '<div class="grid">' +
        stat("Tests done", s.completed + (s.pending ? " (+" + s.pending + ")" : "")) +
        stat("Avg return", pct(s.avg_return, true), cls(s.avg_return)) +
        stat("Win rate", pct(s.win_rate)) +
        stat("Avg vs SPY", pct(s.avg_excess_vs_spy, true), cls(s.avg_excess_vs_spy)) +
        "</div>";
    }).catch(function () { /* no backtest yet - fine */ });
  }

  var market = null;

  function loadMarket() {
    fetchJSON("data/market.json").then(function (m) { market = m; renderMovers(); })
      .catch(function () { market = null; renderMovers(); });
  }

  function renderMovers() {
    var head = $("#movers-head");
    if (!market || !market.market_date) {
      head.innerHTML = '<p class="muted small">No market data yet - it appears after the next scan.</p>';
      $("#movers-gainers").innerHTML = $("#movers-losers").innerHTML = "";
      return;
    }
    var big = (market.drops || []).length;
    head.innerHTML = "<h2>S&amp;P 500 · " + esc(market.market_date) + "</h2>" +
      '<div class="breadth"><span class="pos">▲ ' + (market.advancers || 0) + " up</span>" +
      '<span class="neg">▼ ' + (market.decliners || 0) + " down</span>" +
      (market.median_pct != null ? "<span>typical stock " + (market.median_pct > 0 ? "+" : "") +
        market.median_pct.toFixed(2) + "%</span>" : "") +
      "<span>" + (big ? '<b class="neg">' + big + " fell " + esc(market.threshold_pct) + "%+</b>" :
        "none fell " + esc(market.threshold_pct) + "%+") + "</span></div>";
    var held = {};
    ((data && data.tickers) || []).forEach(function (t) { held[t.ticker] = t; });
    function rowsHtml(rows, what) {
      return rows.slice(0, 10).map(function (m, i) {
      var bigDrop = m.pct <= -Math.abs(market.threshold_pct);
      var w = held[m.ticker];
      return '<div class="mv"><div><span class="muted">' + (i + 1) + '.</span> <span class="sym">' + esc(m.ticker) + "</span> " +
        (bigDrop ? '<span class="badge big">' + esc(market.threshold_pct) + "%+ drop</span> " : "") +
        (w ? '<span class="badge src">watchlist ' + w.score.toFixed(1) + "</span>" : "") +
        '<div class="nm">' + esc(m.name) + (m.sector ? " · " + esc(m.sector) : "") + "</div></div>" +
        '<div><div class="pct ' + (m.pct > 0 ? "pos" : "neg") + '">' + (m.pct > 0 ? "+" : "") + m.pct.toFixed(2) +
        '%</div><div class="px">$' + Number(m.close).toFixed(2) + "</div></div>" +
        '<div class="links"><a href="https://finance.yahoo.com/quote/' + encodeURIComponent(m.ticker) +
        '/news" target="_blank" rel="noopener">Why? (news)</a>' +
        '<button type="button" class="link" data-trade="' + esc(m.ticker) + '" data-price="' + esc(m.close) +
        '" data-reason="' + esc((m.pct > 0 ? "Up " : "Down ") + Math.abs(m.pct).toFixed(1) + "% on " + market.market_date) +
        '">Paper-trade</button></div></div>';
      }).join("") || '<div class="card empty">No ' + what + " today.</div>";
    }
    $("#movers-gainers").innerHTML = rowsHtml(market.gainers || [], "gainers");
    $("#movers-losers").innerHTML = rowsHtml(market.losers || [], "decliners");
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-trade]");
    if (!b) return;
    var f = $("#trade-form");
    f.ticker.value = b.dataset.trade;
    f.price.value = b.dataset.price ? Number(b.dataset.price).toFixed(2) : "";
    f.reason.value = b.dataset.reason || "";
    f.date.value = today();
    showTab("paper");
    f.amount.focus();
  });
  $("#refresh").addEventListener("click", function () { loadSignals(); loadTrack(); loadTrending(); loadMarket(); });

  // ------------------------------------------------------------ trending view
  var trending = null;

  function repoUrl() {
    // https://OWNER.github.io/REPO/ -> https://github.com/OWNER/REPO
    var m = location.hostname.match(/^([^.]+)\.github\.io$/);
    var repo = location.pathname.split("/").filter(Boolean)[0];
    return m && repo ? "https://github.com/" + m[1] + "/" + repo : "";
  }

  function loadTrending() {
    fetchJSON("data/trending.json").then(function (t) { trending = t; renderTrending(); })
      .catch(function () {
        $("#trend-rows").innerHTML = '<div class="card empty">No trending data yet - it appears after the next scan.</div>';
      });
  }

  function renderTrending() {
    var t = trending;
    if (!t) return;
    var note = $("#trend-note");
    note.hidden = !t.note;
    note.textContent = t.note || "";
    if (t.status !== "ok") {
      $("#trend-rows").innerHTML = '<div class="card empty">No trending data yet - it appears after the next scan.</div>';
      $("#trend-private").hidden = true;
      $("#trend-meta").textContent = "";
      return;
    }
    var scanned = {};
    ((data && data.tickers) || []).forEach(function (x) { scanned[x.ticker] = x; });
    var edit = repoUrl() ? repoUrl() + "/edit/main/watchlist.json" : "";
    var SRC = { stocktwits: "StockTwits", bluesky: "Bluesky", reddit: "Reddit" };
    $("#trend-rows").innerHTML = (t.rows || []).map(function (r) {
      var cls = { rising: "rising", steady: "steady", "below minimum": "steady" }[r.status] || "building";
      var label = { rising: "RISING", steady: "normal", "below minimum": "quiet" }[r.status] || "new";
      var lines = Object.keys(r.sources || {}).map(function (k) {
        var x = r.sources[k];
        var what = k === "stocktwits" ? Math.round(x.value) + " msgs/day" :
          (k === "reddit" ? x.mentions + " mentions" : Math.round(x.value) + " posts/day");
        return "<div>" + esc(SRC[k] || k) + ": " + what + " by " + x.authors + " people" +
          (x.vs_baseline ? " · " + x.vs_baseline + "× normal" : "") +
          (x.zscore != null ? " · z " + x.zscore.toFixed(1) : "") + "</div>";
      }).join("");
      var s = scanned[r.ticker];
      var act;
      if (r.on_watchlist) act = "On your watchlist" + (s ? " · score " + s.score.toFixed(1) + "/10" : "");
      else if (s) act = "Auto-checked: score <b>" + s.score.toFixed(1) + "/10</b> - see Signals tab";
      else act = (edit ? '<a href="' + esc(edit) + '" target="_blank" rel="noopener">Add to watchlist on GitHub</a>' +
        ' <button type="button" class="link" data-copy=\'' + esc(JSON.stringify({ keyword: r.name, ticker: r.ticker })) +
        '\'>copy line</button>' : "Not on your watchlist");
      return '<div class="card trow"><div class="thead"><span class="sym">' + esc(r.ticker) + '</span><span class="kw">' +
        esc(r.name) + "</span>" +
        (r.stocktwits_trending_rank ? '<span class="badge src">#' + r.stocktwits_trending_rank + " on StockTwits</span>" : "") +
        '<span class="badge ' + cls + '">' + label + "</span></div>" +
        '<div class="meta">' + (lines || "No mentions measured yet") + "</div>" +
        (r.samples || []).slice(0, 2).map(function (q) {
          return '<a class="quote" href="' + esc(q.url) + '" target="_blank" rel="noopener">“' + esc(q.text) +
            "” <small>" + esc(q.sub === "bluesky" || q.sub === "stocktwits" ? (SRC[q.sub]) : "r/" + q.sub) + "</small></a>";
        }).join("") +
        '<div class="act">' + act + "</div></div>";
    }).join("") || '<div class="card empty">Nothing above the minimum mention level right now.</div>';

    var priv = t.private || [];
    $("#trend-private").hidden = !priv.length;
    $("#trend-private").innerHTML = "<h2>Buzzing but private</h2><p class=\"muted small\">No public stock to buy.</p>" +
      '<ul class="plain">' + priv.slice(0, 10).map(function (p) {
        return "<li>" + esc(p.brand) + " - " + p.mentions + " mentions</li>";
      }).join("") + "</ul>";
    $("#trend-meta").textContent = "Sources: " + ((t.sources || []).join(", ") || "none") + " · " +
      (t.generated_at ? "updated " + ago(t.generated_at) : "") + " · " + (t.history_days || 0) + " days of history";
  }

  $("#trend-rows").addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy]");
    if (!b) return;
    var line = b.getAttribute("data-copy") + ",";
    (navigator.clipboard ? navigator.clipboard.writeText(line) : Promise.reject()).then(function () {
      b.textContent = "copied - paste it into the list";
    }).catch(function () { b.textContent = line; });
  });

  // ------------------------------------------------------------ paper trading
  function loadBook() {
    var fallback = { startingCash: (data && data.paper_trading && data.paper_trading.starting_cash) || 10000, trades: [] };
    try {
      var b = JSON.parse(localStorage.getItem(STORE_KEY));
      if (b && Array.isArray(b.trades) && typeof b.startingCash === "number") {
        // Options paper trading was briefly available and then removed; ignore any option trades.
        b.trades = b.trades.filter(function (t) { return t.kind !== "option"; });
        return b;
      }
    } catch (e) {}
    return fallback;
  }
  function saveBook(b) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(b)); return true; }
    catch (e) { $("#settings-msg").textContent = "Couldn't save (browser storage blocked or full)."; return false; }
  }
  function marks() {
    var m = {};
    ((data && data.tickers) || []).forEach(function (t) { if (t.last_close) m[t.ticker] = t.last_close; });
    return m;
  }
  function stat(k, v, c) {
    return '<div class="stat"><div class="k">' + esc(k) + '</div><div class="v ' + (c || "") + '">' + esc(v) + "</div></div>";
  }

  function renderPaper() {
    var book = loadBook();
    var m = marks();
    var p = PT.portfolio(book.trades, book.startingCash, m);
    var hold = (data && data.hold_days) || 10;
    $("#stats").innerHTML =
      stat("Cash", money(p.cash)) +
      stat("Account value", money(p.equity), cls(p.equity - p.startingCash)) +
      stat("Realized P/L", money(p.realizedPL, true), cls(p.realizedPL)) +
      stat("Unrealized P/L", p.openCount ? money(p.unrealizedPL, true) + (p.unmarked ? "*" : "") : "—", cls(p.unrealizedPL)) +
      stat("Win rate", p.winRate == null ? "—" : pct(p.winRate) + " (" + p.wins + "/" + p.closedCount + ")") +
      stat("Avg trade", pct(p.avgReturnPct, true), cls(p.avgReturnPct));

    var open = book.trades.filter(function (t) { return !t.exitDate; });
    var closed = book.trades.filter(function (t) { return t.exitDate; })
      .sort(function (a, b) { return a.exitDate < b.exitDate ? 1 : -1; });

    $("#open-trades").innerHTML = open.length ? open.map(function (t) {
      var u = PT.tradePL(t, m[t.ticker]);
      var exitBy = PT.addTradingDays(t.entryDate, hold);
      var due = today() >= exitBy;
      return '<div class="trade" data-id="' + esc(t.id) + '">' +
        '<div class="l1"><span>' + esc(t.ticker) + " · " + money(t.amount) + "</span>" +
        (u ? '<span class="' + cls(u.pl) + '">' + money(u.pl, true) + " (" + pct(u.pct, true) + ")</span>"
           : '<span class="muted small">no live price</span>') + "</div>" +
        '<div class="l2">Bought ' + esc(t.entryDate) + " @ $" + t.entryPrice.toFixed(2) + " · " +
        t.shares.toFixed(3) + " sh · " + (due ? "<b>" : "") + "planned exit " + exitBy + " (" + hold + "-day hold)" +
        (due ? "</b>" : "") + (u ? " · marked at last close $" + Number(m[t.ticker]).toFixed(2) : "") + "</div>" +
        (t.reason ? '<div class="why">' + esc(t.reason) + "</div>" : "") +
        '<div class="actions"><button type="button" class="link" data-act="close">Close trade</button>' +
        '<button type="button" class="link danger" data-act="delete">Delete</button></div>' +
        "</div>";
    }).join("") : '<div class="empty">No open paper trades.</div>';

    $("#closed-trades").innerHTML = closed.length ? closed.map(function (t) {
      var r = PT.tradePL(t);
      return '<div class="trade" data-id="' + esc(t.id) + '">' +
        '<div class="l1"><span>' + esc(t.ticker) + " · " + money(t.amount) + '</span><span class="' + cls(r.pl) + '">' +
        money(r.pl, true) + " (" + pct(r.pct, true) + ")</span></div>" +
        '<div class="l2">' + esc(t.entryDate) + " @ $" + t.entryPrice.toFixed(2) + " → " + esc(t.exitDate) +
        " @ $" + t.exitPrice.toFixed(2) + " · " + PT.daysBetween(t.entryDate, t.exitDate) + " days</div>" +
        (t.reason ? '<div class="why">' + esc(t.reason) + "</div>" : "") +
        '<div class="actions"><button type="button" class="link danger" data-act="delete">Delete</button></div>' +
        "</div>";
    }).join("") : '<div class="empty">Nothing closed yet.</div>';

    $("#ticker-list").innerHTML = ((data && data.tickers) || []).map(function (t) {
      return '<option value="' + esc(t.ticker) + '">' + esc(t.keyword) + "</option>";
    }).join("");
    $("#cash-form").cash.value = book.startingCash;
  }

  $("#trade-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    var book = loadBook();
    var input = { ticker: f.ticker.value, date: f.date.value, price: f.price.value, amount: f.amount.value, reason: f.reason.value };
    var cash = PT.portfolio(book.trades, book.startingCash).cash;
    var errs = PT.validateOpen(input, cash);
    $("#form-errors").innerHTML = errs.map(esc).join("<br>");
    if (errs.length) return;
    book.trades.push(PT.openTrade(input));
    if (saveBook(book)) {
      f.reset();
      f.date.value = today();
      renderPaper();
    }
  });

  function confirmable(btn, label, action) {
    // The two-tap confirm avoids window.confirm(), which home-screen apps can block.
    if (btn.dataset.armed) { action(); return; }
    var old = btn.textContent;
    btn.dataset.armed = "1";
    btn.textContent = label;
    setTimeout(function () { btn.textContent = old; delete btn.dataset.armed; }, 3000);
  }

  function tradeClick(e) {
    var btn = e.target.closest("button");
    if (!btn) return;
    var card = btn.closest(".trade");
    var id = card && card.dataset.id;
    var book = loadBook();
    var idx = book.trades.findIndex(function (t) { return t.id === id; });
    if (idx < 0) return;
    var act = btn.dataset.act;
    if (act === "delete") {
      confirmable(btn, "Tap again to delete", function () {
        book.trades.splice(idx, 1);
        saveBook(book);
        renderPaper();
      });
    } else if (act === "close") {
      if (card.querySelector(".close-form")) return;
      var t = book.trades[idx];
      var last = marks()[t.ticker];
      var form = document.createElement("form");
      form.className = "close-form";
      form.noValidate = true;
      form.innerHTML = '<div class="grid2"><label>Exit date<input name="date" type="date" value="' + today() +
        '"></label><label>Exit price<input name="price" inputmode="decimal" value="' +
        (last ? Number(last).toFixed(2) : "") + '"></label></div><div class="errors"></div>' +
        '<div class="row"><button type="submit" class="primary">Confirm close</button>' +
        '<button type="button" data-act="cancel">Cancel</button></div>';
      card.appendChild(form);
      form.price.focus();
    } else if (act === "cancel") {
      btn.closest(".close-form").remove();
    }
  }
  function closeSubmit(e) {
    if (!e.target.classList.contains("close-form")) return;
    e.preventDefault();
    var form = e.target;
    var id = form.closest(".trade").dataset.id;
    var book = loadBook();
    var idx = book.trades.findIndex(function (t) { return t.id === id; });
    var input = { date: form.date.value, price: form.price.value };
    var errs = PT.validateClose(book.trades[idx], input);
    form.querySelector(".errors").innerHTML = errs.map(esc).join("<br>");
    if (errs.length) return;
    book.trades[idx] = PT.closeTrade(book.trades[idx], input);
    saveBook(book);
    renderPaper();
  }
  ["#open-trades", "#closed-trades"].forEach(function (s) {
    $(s).addEventListener("click", tradeClick);
    $(s).addEventListener("submit", closeSubmit);
  });

  $("#cash-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var v = parseFloat(String(e.target.cash.value).replace(/[$,\s]/g, ""));
    var msg = $("#settings-msg");
    if (!(v > 0)) { msg.textContent = "Starting cash must be a positive number."; return; }
    var book = loadBook();
    book.startingCash = v;
    if (saveBook(book)) msg.textContent = "Starting cash saved.";
    renderPaper();
  });

  $("#export").addEventListener("click", function () {
    var blob = new Blob([JSON.stringify(loadBook(), null, 1)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "paper-trades-" + today() + ".json";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    $("#settings-msg").textContent = "Backup downloaded.";
  });

  $("#import").addEventListener("change", function (e) {
    var file = e.target.files[0];
    if (!file) return;
    file.text().then(function (txt) {
      var b = JSON.parse(txt);
      if (!b || !Array.isArray(b.trades) || typeof b.startingCash !== "number") throw new Error("not a backup file");
      saveBook(b);
      renderPaper();
      $("#settings-msg").textContent = "Imported " + b.trades.length + " trades.";
    }).catch(function (err) {
      $("#settings-msg").textContent = "Import failed: " + err.message;
    });
    e.target.value = "";
  });

  $("#reset").addEventListener("click", function (e) {
    confirmable(e.target, "Tap again to erase everything", function () {
      var book = loadBook();
      book.trades = [];
      saveBook(book);
      renderPaper();
      $("#settings-msg").textContent = "All paper trades erased.";
    });
  });

  // ------------------------------------------------------------ boot
  $("#trade-form").date.value = today();
  var startTab = "signals";
  try { startTab = localStorage.getItem("trendscanner.tab") || "signals"; } catch (e) {}
  showTab(["paper", "trending", "movers"].indexOf(startTab) >= 0 ? startTab : "signals");
  loadSignals();
  loadTrack();
  loadTrending();
  loadMarket();

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(function () {});
  }
})();
