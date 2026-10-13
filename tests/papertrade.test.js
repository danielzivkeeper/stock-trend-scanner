// Offline tests for the paper-trading P/L math. Run:  node --test tests/papertrade.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const PT = require("../docs/papertrade.js");

const close = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);
const buy = (ticker, price, amount, date = "2026-09-01", id) =>
  PT.openTrade({ ticker, date, price, amount }, id || ticker + price);

test("opening a trade computes fractional shares", () => {
  const t = buy("celh", 40, 1000);
  assert.equal(t.ticker, "CELH");
  close(t.shares, 25);
  assert.equal(t.exitDate, null);
});

test("closed trade P/L and percent", () => {
  const t = PT.closeTrade(buy("AAA", 50, 1000), { date: "2026-09-15", price: 55 });
  const r = PT.tradePL(t);
  close(r.pl, 100);
  close(r.pct, 0.1);
  close(r.value, 1100);
});

test("losing trade", () => {
  const r = PT.tradePL(PT.closeTrade(buy("AAA", 80, 2000), { date: "2026-09-02", price: 60 }));
  close(r.pl, -500);
  close(r.pct, -0.25);
});

test("open trade P/L only with a mark price", () => {
  const t = buy("AAA", 10, 500);
  assert.equal(PT.tradePL(t), null);
  close(PT.tradePL(t, 12).pl, 100);
});

test("portfolio: cash, realized P/L, win rate, equity", () => {
  const trades = [
    PT.closeTrade(buy("W1", 100, 1000), { date: "2026-09-10", price: 110 }), // +100
    PT.closeTrade(buy("L1", 100, 2000), { date: "2026-09-10", price: 95 }),  // -100
    PT.closeTrade(buy("W2", 20, 500), { date: "2026-09-10", price: 30 }),    // +250
    PT.closeTrade(buy("BE", 10, 300), { date: "2026-09-10", price: 10 }),    // 0 -> not a win
    buy("OPEN", 50, 1500),                                                    // open, marked at 60 -> +300
    buy("NOMARK", 5, 400),                                                    // open, no mark
  ];
  const p = PT.portfolio(trades, 10000, { OPEN: 60 });
  close(p.realizedPL, 250);
  close(p.invested, 1900);
  close(p.cash, 10000 - 1900 + 250);   // 8350
  close(p.unrealizedPL, 300);
  close(p.openValue, 1800 + 400);       // marked + at-cost
  close(p.equity, 8350 + 2200);         // 10550
  assert.equal(p.closedCount, 4);
  assert.equal(p.openCount, 2);
  assert.equal(p.wins, 2);
  assert.equal(p.losses, 2);
  close(p.winRate, 0.5);
  close(p.avgReturnPct, (0.1 - 0.05 + 0.5 + 0) / 4);
  assert.equal(p.unmarked, 1);
});

test("empty portfolio has null win rate, not 0% or NaN", () => {
  const p = PT.portfolio([], 10000);
  assert.equal(p.winRate, null);
  close(p.cash, 10000);
  close(p.equity, 10000);
});

test("validation: open", () => {
  assert.deepEqual(PT.validateOpen({ ticker: "CELH", date: "2026-09-01", price: "40", amount: "$1,000" }, 5000), []);
  assert.equal(PT.validateOpen({ ticker: "", date: "2026-09-01", price: 1, amount: 1 }).length, 1);
  assert.equal(PT.validateOpen({ ticker: "A", date: "2026-02-30", price: 1, amount: 1 }).length, 1);
  assert.equal(PT.validateOpen({ ticker: "A", date: "2026-02-03", price: 0, amount: -5 }).length, 2);
  assert.match(PT.validateOpen({ ticker: "A", date: "2026-02-03", price: 1, amount: 6000 }, 5000)[0], /Not enough/);
});

test("validation: close", () => {
  const t = buy("AAA", 10, 100, "2026-09-10");
  assert.deepEqual(PT.validateClose(t, { date: "2026-09-10", price: 11 }), []);
  assert.match(PT.validateClose(t, { date: "2026-09-09", price: 11 })[0], /before the entry/);
  assert.equal(PT.validateClose(t, { date: "2026-09-11", price: 0 }).length, 1);
  const closed = PT.closeTrade(t, { date: "2026-09-12", price: 12 });
  assert.match(PT.validateClose(closed, { date: "2026-09-13", price: 12 })[0], /already closed/);
});

test("closing does not mutate the original trade", () => {
  const t = buy("AAA", 10, 100);
  PT.closeTrade(t, { date: "2026-09-12", price: 12 });
  assert.equal(t.exitDate, null);
});

test("suggested exit: N trading days skips weekends", () => {
  assert.equal(PT.addTradingDays("2026-10-02", 1), "2026-10-05");   // Fri -> Mon
  assert.equal(PT.addTradingDays("2026-10-01", 10), "2026-10-15");  // Thu + 10 trading days
});

// ------------------------------------------------------------ options
const call = (premium = 2.35, contracts = 2, extra = {}) => PT.openOption(Object.assign({
  ticker: "celh", optType: "call", strike: 45, expiry: "2026-11-20", date: "2026-10-13",
  contracts, premium }, extra), "opt1");

test("buying options: cost = premium x 100 x contracts", () => {
  const t = call();
  assert.equal(t.kind, "option");
  assert.equal(t.ticker, "CELH");
  close(t.amount, 470);
  assert.equal(t.shares, 200);
  assert.equal(PT.optionLabel(t), "CELH $45 CALL exp 2026-11-20");
});

test("sell to close: P/L from premium change", () => {
  const r = PT.tradePL(PT.closeTrade(call(), { date: "2026-10-20", price: 3.10 }));
  close(r.pl, (3.10 - 2.35) * 200);   // +150
  close(r.pct, 3.10 / 2.35 - 1);
});

test("selling for $0 is allowed for options (total loss) but not for stock", () => {
  const t = call();
  assert.deepEqual(PT.validateClose(t, { date: "2026-10-20", price: 0 }), []);
  const r = PT.tradePL(PT.closeTrade(t, { date: "2026-10-20", price: 0 }));
  close(r.pl, -470);
  close(r.pct, -1);
  assert.equal(PT.validateClose(buy("AAA", 10, 100), { date: "2026-10-20", price: 0 }).length, 1);
});

test("intrinsic value and breakeven", () => {
  close(PT.intrinsic("call", 45, 50), 5);
  close(PT.intrinsic("call", 45, 40), 0);
  close(PT.intrinsic("put", 45, 40), 5);
  close(PT.intrinsic("put", 45, 50), 0);
  close(PT.breakeven(call()), 47.35);
  close(PT.breakeven(call(1, 1, { optType: "put" })), 44);
});

test("expiration: in the money settles at intrinsic, out of the money at $0", () => {
  const itm = PT.expireOption(call(), { underlying: 50 });
  assert.equal(itm.exitDate, "2026-11-20");
  close(itm.exitPrice, 5);
  close(PT.tradePL(itm).pl, (5 - 2.35) * 200);     // +530
  assert.equal(itm.exitReason, "expired in the money");
  const otm = PT.expireOption(call(), { underlying: 44 });
  close(PT.tradePL(otm).pl, -470);
  assert.equal(otm.exitReason, "expired worthless");
  const put = PT.expireOption(call(1.5, 1, { optType: "put", strike: 40 }), { underlying: 36 });
  close(PT.tradePL(put).pl, (4 - 1.5) * 100);       // +250
});

test("option validation", () => {
  const ok = { ticker: "CELH", optType: "call", strike: "45", expiry: "2026-11-20", date: "2026-10-13",
               contracts: "2", premium: "2.35" };
  assert.deepEqual(PT.validateOpenOption(ok, 10000), []);
  assert.match(PT.validateOpenOption(ok, 400)[0], /Not enough paper cash: this costs \$470/);
  assert.equal(PT.validateOpenOption(Object.assign({}, ok, { contracts: "1.5" }), 10000).length, 1);
  assert.equal(PT.validateOpenOption(Object.assign({}, ok, { expiry: "2026-10-01" }), 10000).length, 1);
  assert.equal(PT.validateOpenOption(Object.assign({}, ok, { optType: "" }), 10000).length, 1);
  assert.equal(PT.validateExpire(call(), { underlying: "" }).length, 1);
});

test("portfolio mixes stocks and options; open options are held at cost, never marked with the stock price", () => {
  const trades = [
    PT.closeTrade(buy("AAA", 100, 1000), { date: "2026-10-10", price: 110 }),   // stock +100
    PT.expireOption(call(), { underlying: 44 }),                                 // option -470
    call(1.00, 3, { ticker: "BBB" }),                                            // open option, $300
  ];
  const p = PT.portfolio(trades, 10000, { BBB: 999, CELH: 999 });
  close(p.realizedPL, -370);
  close(p.byKind.stock.realizedPL, 100);
  close(p.byKind.option.realizedPL, -470);
  assert.equal(p.byKind.option.open, 1);
  close(p.cash, 10000 - 300 - 370);
  close(p.unrealizedPL, 0);          // the 999 stock price must NOT be used for the option
  close(p.equity, 10000 - 370);
  assert.equal(p.unmarked, 1);
  close(p.winRate, 0.5);
});
