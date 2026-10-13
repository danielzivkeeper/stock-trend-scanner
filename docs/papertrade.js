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
    var p = num(input.price);
    if (trade.kind === "option") {
      // An option can be sold for $0 (worthless), but not for a negative price.
      if (!(p >= 0)) errs.push("Enter the premium you sold for (0 if worthless).");
    } else if (!(p > 0)) errs.push("Exit price must be greater than 0.");
    return errs;
  }

  // ------------------------------------------------------------ options (buying only)
  // One contract = 100 shares. Premiums are quoted per share: a 2.35 premium
  // costs $235 per contract. Selling/writing options is deliberately not
  // supported - it needs margin and can lose more than you put in.
  var MULTIPLIER = 100;

  function validateOpenOption(input, cash) {
    var errs = [];
    var t = String(input.ticker || "").trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(t)) errs.push("Enter the stock's ticker, like CELH.");
    if (input.optType !== "call" && input.optType !== "put") errs.push("Choose call or put.");
    if (!(num(input.strike) > 0)) errs.push("Strike price must be greater than 0.");
    if (!isValidDate(input.date)) errs.push("Enter a valid purchase date.");
    if (!isValidDate(input.expiry)) errs.push("Enter a valid expiration date.");
    else if (isValidDate(input.date) && input.expiry < input.date) errs.push("Expiration can't be before the purchase date.");
    var c = num(input.contracts), p = num(input.premium);
    if (!(c >= 1) || Math.floor(c) !== c) errs.push("Contracts must be a whole number (1 or more).");
    if (!(p > 0)) errs.push("Premium must be greater than 0 (the price per share, e.g. 2.35).");
    if (!errs.length && typeof cash === "number" && p * c * MULTIPLIER > cash + EPS)
      errs.push("Not enough paper cash: this costs $" + (p * c * MULTIPLIER).toFixed(2) +
                ", you have $" + cash.toFixed(2) + ".");
    return errs;
  }

  function openOption(input, id) {
    var premium = num(input.premium), contracts = num(input.contracts);
    var shares = contracts * MULTIPLIER;
    return {
      id: id || String(Date.now()) + Math.random().toString(36).slice(2, 7),
      kind: "option",
      ticker: String(input.ticker).trim().toUpperCase(),
      optType: input.optType,
      strike: num(input.strike),
      expiry: input.expiry,
      contracts: contracts,
      entryDate: input.date,
      entryPrice: premium,       // per share, so tradePL works the same as for stock
      shares: shares,
      amount: premium * shares,  // total cost
      reason: String(input.reason || "").trim(),
      exitDate: null,
      exitPrice: null
    };
  }

  /** Value per share if exercised right now: calls max(S-K, 0), puts max(K-S, 0). */
  function intrinsic(optType, strike, underlying) {
    return Math.max(0, optType === "call" ? underlying - strike : strike - underlying);
  }

  /** Stock price at expiration where the trade breaks even (premium paid back). */
  function breakeven(trade) {
    return trade.optType === "call" ? trade.strike + trade.entryPrice : trade.strike - trade.entryPrice;
  }

  function validateExpire(trade, input) {
    var errs = [];
    if (trade.exitDate) errs.push("This trade is already closed.");
    if (!(num(input.underlying) > 0)) errs.push("Enter the stock's closing price on the expiration date.");
    return errs;
  }

  /** Settle at expiration: in-the-money options are worth their intrinsic value, others $0. */
  function expireOption(trade, input) {
    var out = Object.assign({}, trade);
    out.exitDate = trade.expiry;
    out.underlyingAtExit = num(input.underlying);
    out.exitPrice = intrinsic(trade.optType, trade.strike, out.underlyingAtExit);
    out.exitReason = out.exitPrice > 0 ? "expired in the money" : "expired worthless";
    return out;
  }

  function optionLabel(trade) {
    return trade.ticker + " $" + (+trade.strike).toFixed(2).replace(/\.00$/, "") + " " +
      (trade.optType === "call" ? "CALL" : "PUT") + " exp " + trade.expiry;
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
    if (px == null || !(px >= 0) || (!trade.exitDate && !(px > 0))) return null;  // options can close at $0
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
   *   unrealizedPL / equity use `marks` {TICKER: lastPrice} for open STOCK trades;
   *   open options (no free live option quotes) and unmarked stocks are valued at cost.
   *   byKind splits realized P/L and counts between stock and option trades.
   */
  function portfolio(trades, startingCash, marks) {
    marks = marks || {};
    var s = {
      startingCash: startingCash, cash: startingCash, invested: 0, realizedPL: 0,
      unrealizedPL: 0, openValue: 0, equity: 0, openCount: 0, closedCount: 0,
      wins: 0, losses: 0, winRate: null, unmarked: 0, avgReturnPct: null,
      byKind: { stock: { realizedPL: 0, closed: 0, open: 0 }, option: { realizedPL: 0, closed: 0, open: 0 } }
    };
    var pctSum = 0;
    trades.forEach(function (t) {
      var k = s.byKind[t.kind === "option" ? "option" : "stock"];
      if (t.exitDate) {
        var r = tradePL(t);
        k.closed++;
        k.realizedPL += r.pl;
        s.closedCount++;
        s.realizedPL += r.pl;
        s.cash += r.pl; // got the stake back plus/minus P/L
        pctSum += r.pct;
        if (r.pl > EPS) s.wins++; else s.losses++;
      } else {
        s.openCount++;
        k.open++;
        s.invested += t.amount;
        s.cash -= t.amount;
        var u = t.kind === "option" ? null : tradePL(t, marks[t.ticker]);
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
    addTradingDays: addTradingDays, daysBetween: daysBetween,
    MULTIPLIER: MULTIPLIER, validateOpenOption: validateOpenOption, openOption: openOption,
    intrinsic: intrinsic, breakeven: breakeven, validateExpire: validateExpire, expireOption: expireOption,
    optionLabel: optionLabel
  };
});
