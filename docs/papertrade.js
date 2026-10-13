/* Paper-trading math. Pure functions only - no DOM, no storage - so the same
 * file runs in the browser (window.PaperTrade) and in Node tests (require). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PaperTrade = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var EPS = 1e-9;
  var DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

  function isValidDate(s) {
    if (typeof s !== "string" || !DATE_RE.test(s)) return false;
    var d = new Date(s + "T00:00:00Z");
    return !isNaN(d) && d.toISOString().slice(0, 10) === s;
  }

  function num(x) {
    var n = typeof x === "number" ? x : parseFloat(String(x).replace(/[$,\s]/g, ""));
    return isFinite(n) ? n : NaN;
  }

  /** Returns a list of human-readable problems ([] = OK). */
  function validateOpen(input, cash) {
    var errs = [];
    var t = String(input.ticker || "").trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(t)) errs.push("Enter a ticker symbol like CELH.");
    if (!isValidDate(input.date)) errs.push("Enter a valid entry date.");
    var p = num(input.price), a = num(input.amount);
    if (!(p > 0)) errs.push("Entry price must be greater than 0.");
    if (!(a > 0)) errs.push("Dollar amount must be greater than 0.");
    else if (typeof cash === "number" && a > cash + EPS)
      errs.push("Not enough paper cash: you have $" + cash.toFixed(2) + ".");
    return errs;
  }

  function validateClose(trade, input) {
    var errs = [];
    if (trade.exitDate) errs.push("This trade is already closed.");
    if (!isValidDate(input.date)) errs.push("Enter a valid exit date.");
    else if (input.date < trade.entryDate) errs.push("Exit date can't be before the entry date.");
    if (!(num(input.price) > 0)) errs.push("Exit price must be greater than 0.");
    return errs;
  }

  function openTrade(input, id) {
    var price = num(input.price), amount = num(input.amount);
    return {
      id: id || String(Date.now()) + Math.random().toString(36).slice(2, 7),
      ticker: String(input.ticker).trim().toUpperCase(),
      entryDate: input.date,
      entryPrice: price,
      amount: amount,
      shares: amount / price, // fractional shares keep the math exact
      reason: String(input.reason || "").trim(),
      exitDate: null,
      exitPrice: null
    };
  }

  function closeTrade(trade, input) {
    var out = Object.assign({}, trade);
    out.exitDate = input.date;
    out.exitPrice = num(input.price);
    return out;
  }

  /** Realized P/L for a closed trade, or unrealized P/L at `markPrice` for an open one. */
  function tradePL(trade, markPrice) {
    var px = trade.exitDate ? trade.exitPrice : markPrice;
    if (!(px > 0)) return null;
    var value = trade.shares * px;
    return { value: value, pl: value - trade.amount, pct: px / trade.entryPrice - 1 };
  }

  function daysBetween(a, b) {
    return Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 86400000);
  }

  /** Calendar date `hold` trading days (Mon-Fri, ignoring holidays) after `date`. */
  function addTradingDays(date, hold) {
    var d = new Date(date + "T00:00:00Z");
    var left = hold;
    while (left > 0) {
      d.setUTCDate(d.getUTCDate() + 1);
      var wd = d.getUTCDay();
      if (wd !== 0 && wd !== 6) left--;
    }
    return d.toISOString().slice(0, 10);
  }

  /**
   * Portfolio summary.
   *   cash        = starting cash - money in open trades + proceeds of closed trades
   *   realizedPL  = sum of closed-trade P/L
   *   winRate     = closed trades with P/L > 0 / closed trades (null when none closed;
   *                 a break-even trade counts as a non-win)
   *   unrealizedPL / equity use `marks` {TICKER: lastPrice} when available; open
   *   trades without a mark are valued at cost.
   */
  function portfolio(trades, startingCash, marks) {
    marks = marks || {};
    var s = {
      startingCash: startingCash, cash: startingCash, invested: 0, realizedPL: 0,
      unrealizedPL: 0, openValue: 0, equity: 0, openCount: 0, closedCount: 0,
      wins: 0, losses: 0, winRate: null, unmarked: 0, avgReturnPct: null
    };
    var pctSum = 0;
    trades.forEach(function (t) {
      if (t.exitDate) {
        var r = tradePL(t);
        s.closedCount++;
        s.realizedPL += r.pl;
        s.cash += r.pl; // got the stake back plus/minus P/L
        pctSum += r.pct;
        if (r.pl > EPS) s.wins++; else s.losses++;
      } else {
        s.openCount++;
        s.invested += t.amount;
        s.cash -= t.amount;
        var u = tradePL(t, marks[t.ticker]);
        if (u) { s.unrealizedPL += u.pl; s.openValue += u.value; }
        else { s.openValue += t.amount; s.unmarked++; }
      }
    });
    if (s.closedCount) {
      s.winRate = s.wins / s.closedCount;
      s.avgReturnPct = pctSum / s.closedCount;
    }
    s.equity = s.cash + s.openValue;
    return s;
  }

  return {
    isValidDate: isValidDate, validateOpen: validateOpen, validateClose: validateClose,
    openTrade: openTrade, closeTrade: closeTrade, tradePL: tradePL, portfolio: portfolio,
    addTradingDays: addTradingDays, daysBetween: daysBetween
  };
});
