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
    $("#tab-signals").hidden = name !== "signals";
    $("#tab-paper").hidden = name !== "paper";
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
    social_spike: "Social spike"
  };

  function loadSignals() {
    $("#load-error").hidden = true;
    $("#updated").textContent = "Loading…";
    return fetchJSON("data/results.json").then(function (d) {
      data = d;
      renderSignals();
      renderPaper();
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

    var thr = d.alert_threshold;
    $("#tickers").innerHTML = (d.tickers || []).map(function (t) {
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
        "</span>" + (t.alert ? '<span class="badge">ALERT</span>' : "") +
        '<span class="score">' + t.score.toFixed(1) + "</span></div>" +
        '<div class="bar' + (t.alert ? " hot" : "") + '" role="img" aria-label="Score ' + t.score + ' of 10">' +
        '<i style="width:' + Math.max(0, Math.min(100, t.score * 10)) + '%"></i>' +
        '<b style="left:calc(' + thr * 10 + '% - 1px)" title="alert threshold"></b></div>' +
        '<div class="fired-line">' + (fired.length ? "Fired: " + fired.map(function (s) {
          return esc(LABEL[s.name] || s.name);
        }).join(", ") : "No signals fired") +
        (t.last_close ? " · last close $" + Number(t.last_close).toFixed(2) : "") + "</div>" +
        "</summary>" +
        '<div class="tbody">' + rows +
        '<p class="math">' + esc(t.explanation[t.explanation.length - 1]) + "</p>" +
        '<button type="button" class="link" data-trade="' + esc(t.ticker) + '" data-price="' +
        esc(t.last_close || "") + '" data-reason="' + esc("Score " + t.score.toFixed(1) +
          (fired.length ? ": " + fired.map(function (s) { return LABEL[s.name] || s.name; }).join(" + ") : "")) +
        '">Paper-trade ' + esc(t.ticker) + " →</button>" +
        '<details class="raw"><summary>Raw data (debugging)</summary><pre>' +
        esc(JSON.stringify(raw, null, 1)) + "</pre></details>" +
        "</div></details>";
    }).join("") || '<div class="card empty">Watchlist is empty - edit watchlist.json on GitHub.</div>';
    renderAbout();
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

  $("#tickers").addEventListener("click", function (e) {
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
  $("#refresh").addEventListener("click", function () { loadSignals(); loadTrack(); });

  // ------------------------------------------------------------ paper trading
  function loadBook() {
    var fallback = { startingCash: (data && data.paper_trading && data.paper_trading.starting_cash) || 10000, trades: [] };
    try {
      var b = JSON.parse(localStorage.getItem(STORE_KEY));
      if (b && Array.isArray(b.trades) && typeof b.startingCash === "number") return b;
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
  showTab(startTab === "paper" ? "paper" : "signals");
  loadSignals();
  loadTrack();

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(function () {});
  }
})();
