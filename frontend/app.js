/* Overlap: dashboard logic.
 *
 * The page loads one JSON file (data/dashboard.json) exported by the pipeline
 * and computes every figure in the browser, so the global filters (year,
 * chamber, party) can recompute everything instantly. No framework: the data
 * is small (a few thousand rows) and plain DOM + SVG strings keep the code
 * readable for review.
 */
"use strict";

const DATA_URL = "data/dashboard.json";
const DEADLINE_DAYS = 45;
const SVGNS = "http://www.w3.org/2000/svg";

const COMMITTEE_SHORT = {
  HSBA: "Financial Services", HSIF: "Energy & Commerce", HSAS: "Armed Services",
  HSAG: "Agriculture", HSPW: "Transportation", HSWM: "Ways & Means",
  HSSY: "Science & Tech", SSBK: "Banking", SSAS: "Armed Services",
  SSCM: "Commerce", SSEG: "Energy", SSHR: "HELP", SSAF: "Agriculture",
};
const PARTY_NAME = { D: "Democrat", R: "Republican", I: "Independent" };

const state = {
  view: "overview",
  year: "all",
  chamber: "all",
  party: "all",
  trades: { q: "", type: "", sector: "", overlap: false, late: false, limit: 50 },
  mi: { limit: 50 },
  members: { sort: "trades", dir: -1 },
};

let DATA = null;
const memberById = new Map();
const committeeById = new Map();

/* ---------------- helpers ---------------- */

const $ = (sel) => document.querySelector(sel);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}
const fmtInt = (n) => n.toLocaleString("en-US");
const fmtPct = (x, digits = 0) => `${(x * 100).toFixed(digits)}%`;

function fmtMoney(n) {
  if (n >= 1e9) return `$${trim(n / 1e9)}B`;
  if (n >= 1e6) return `$${trim(n / 1e6)}M`;
  if (n >= 1e3) return `$${trim(n / 1e3)}K`;
  return `$${n}`;
}
function trim(x) {
  return x >= 100 ? x.toFixed(0) : x >= 10 ? x.toFixed(1).replace(/\.0$/, "") : x.toFixed(1).replace(/\.0$/, "");
}
function fmtMonth(d) {
  return new Date(`${d}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
}
function fmtLongDate(d) {
  return new Date(`${d}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}
function median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
function niceMax(v, step) {
  return Math.max(step, Math.ceil(v / step) * step);
}

function seat(m) {
  return m.chamber === "House"
    ? `${m.state}-${String(m.district).padStart(2, "0")}`
    : `${m.state} · Senate`;
}
function partyTag(m) {
  return `<span class="tag" title="${PARTY_NAME[m.party]}"><i class="pdot p-${m.party}"></i>${m.party} · ${esc(seat(m))}</span>`;
}
function committeeLabel(id) {
  const c = committeeById.get(id);
  return c ? `${c.chamber} ${c.name}` : id;
}
function overseenSectors(m) {
  const set = new Set();
  for (const id of m.committees) for (const s of committeeById.get(id).sectors) set.add(s);
  return set;
}

function bandLabel(t) {
  if (t.amount_max == null) return `Over ${fmtMoney(t.amount_min - 1)}`;
  return `${fmtMoney(t.amount_min - 1 || 1)}–${fmtMoney(t.amount_max)}`;
}
function bandMeter(i, n = 10) {
  let cells = "";
  for (let k = 0; k < n; k++) cells += `<i class="${k === i ? "on" : k < i ? "under" : ""}"></i>`;
  return `<span class="band-cells" aria-hidden="true">${cells}</span>`;
}
function valueRange(trades) {
  let lo = 0, hi = 0, open = false;
  for (const t of trades) {
    lo += t.amount_min;
    if (t.amount_max == null) { hi += t.amount_min; open = true; } else hi += t.amount_max;
  }
  return { lo, hi, open, text: `${fmtMoney(lo)}–${fmtMoney(hi)}${open ? "+" : ""}` };
}
function midpoint(trades) {
  return trades.reduce((s, t) => s + (t.amount_max == null ? t.amount_min : (t.amount_min + t.amount_max) / 2), 0);
}

function lagCell(t) {
  if (t.days_to_file > DEADLINE_DAYS) {
    return `<span class="lag-late" title="Disclosed ${t.days_to_file - DEADLINE_DAYS} days after the 45-day deadline">${t.days_to_file}d late</span>`;
  }
  return `<span class="lag">${t.days_to_file}d</span>`;
}
function retCell(x) {
  if (x == null) return `<span class="muted" title="Not enough days since the trade">–</span>`;
  const cls = x > 0 ? "ret-pos" : x < 0 ? "ret-neg" : "";
  return `<span class="ret ${cls}">${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x * 100).toFixed(1)}%</span>`;
}
const TYPE_LABEL = { buy: "Purchase", sell: "Sale", exchange: "Exchange" };

/* ---------------- filtering + metrics ---------------- */

function filteredTrades() {
  return DATA.trades.filter((t) => {
    const m = memberById.get(t.member_id);
    if (state.year !== "all" && !t.trade_date.startsWith(state.year)) return false;
    if (state.chamber !== "all" && m.chamber !== state.chamber) return false;
    if (state.party !== "all" && m.party !== state.party) return false;
    return true;
  });
}
function filteredMembers() {
  return DATA.members.filter((m) =>
    (state.chamber === "all" || m.chamber === state.chamber) &&
    (state.party === "all" || m.party === state.party));
}

function sectorShares(trades) {
  const counts = new Map();
  for (const t of trades) counts.set(t.sector, (counts.get(t.sector) || 0) + 1);
  const shares = new Map();
  for (const [s, n] of counts) shares.set(s, n / (trades.length || 1));
  return shares;
}

/** Observed overlap share, and the share expected if each member had traded
 *  like Congress as a whole (same filters). */
function overlapStats(trades, baseTrades = trades) {
  const shares = sectorShares(baseTrades);
  let observed = 0, expected = 0;
  const cache = new Map();
  for (const t of trades) {
    if (t.overlap_committee) observed++;
    let e = cache.get(t.member_id);
    if (e === undefined) {
      e = 0;
      for (const s of overseenSectors(memberById.get(t.member_id))) e += shares.get(s) || 0;
      cache.set(t.member_id, e);
    }
    expected += e;
  }
  const n = trades.length || 1;
  return { observed: observed / n, expected: expected / n, count: observed };
}

function memberRollup(trades) {
  const by = new Map();
  for (const t of trades) {
    if (!by.has(t.member_id)) by.set(t.member_id, []);
    by.get(t.member_id).push(t);
  }
  return [...by].map(([id, ts]) => {
    const late = ts.filter((t) => t.days_to_file > DEADLINE_DAYS);
    return {
      m: memberById.get(id),
      trades: ts,
      n: ts.length,
      overlap: ts.filter((t) => t.overlap_committee).length / ts.length,
      late: late.length,
      maxLag: Math.max(...ts.map((t) => t.days_to_file)),
      medLag: median(ts.map((t) => t.days_to_file)),
      value: valueRange(ts),
      mid: midpoint(ts),
    };
  });
}

/* ---------------- tooltip ---------------- */

const tip = () => $("#tip");
function bindTips(root) {
  root.addEventListener("pointermove", (e) => {
    const el = e.target.closest("[data-tip]");
    const t = tip();
    if (!el) { t.hidden = true; return; }
    t.innerHTML = el.getAttribute("data-tip");
    t.hidden = false;
    const pad = 14, r = t.getBoundingClientRect();
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + r.width > window.innerWidth - 8) x = e.clientX - r.width - pad;
    if (y + r.height > window.innerHeight - 8) y = e.clientY - r.height - pad;
    t.style.left = `${Math.max(8, x)}px`;
    t.style.top = `${Math.max(8, y)}px`;
  });
  root.addEventListener("pointerleave", () => { tip().hidden = true; });
}

/* ---------------- charts ---------------- */

function svgWrap(w, h, inner, label) {
  return `<svg xmlns="${SVGNS}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${esc(label)}">${inner}</svg>`;
}

function drawCommitteeChart(el, trades) {
  const w = Math.max(300, el.clientWidth);
  const shares = sectorShares(trades);
  const members = filteredMembers();
  const rows = DATA.committees
    .filter((c) => state.chamber === "all" || c.chamber === state.chamber)
    .map((c) => {
      const memberIds = new Set(members.filter((m) => m.committees.includes(c.id)).map((m) => m.id));
      const ts = trades.filter((t) => memberIds.has(t.member_id));
      const hit = ts.filter((t) => c.sectors.includes(t.sector)).length;
      const expected = c.sectors.reduce((s, x) => s + (shares.get(x) || 0), 0);
      return { c, n: ts.length, hit, observed: ts.length ? hit / ts.length : 0, expected };
    })
    .filter((r) => r.n >= 15)
    .sort((a, b) => (b.observed - b.expected) - (a.observed - a.expected));

  if (!rows.length) { el.innerHTML = `<p class="muted">Not enough trades in this selection.</p>`; return; }

  const labelW = w < 460 ? 132 : 176;
  const right = 44, top = 22, rowH = 30;
  const h = top + rows.length * rowH + 6;
  const max = Math.min(1, niceMax(Math.max(...rows.map((r) => Math.max(r.observed, r.expected))), 0.2));
  const x = (v) => labelW + (v / max) * (w - labelW - right);

  let g = `<g class="grid">`;
  for (let v = 0; v <= max + 1e-9; v += 0.2) {
    g += `<line x1="${x(v)}" x2="${x(v)}" y1="${top - 6}" y2="${h - 4}"/>`;
    g += `<text x="${x(v)}" y="${top - 10}" text-anchor="middle">${Math.round(v * 100)}%</text>`;
  }
  g += `</g>`;

  let body = "";
  rows.forEach((r, i) => {
    const cy = top + i * rowH + rowH / 2;
    const up = r.observed >= r.expected;
    const tipHtml = `<b>${esc(committeeLabel(r.c.id))}</b><br>` +
      `Observed <span class="tip-mono">${fmtPct(r.observed, 1)}</span> (${fmtInt(r.hit)} of ${fmtInt(r.n)} trades)<br>` +
      `Expected <span class="tip-mono">${fmtPct(r.expected, 1)}</span><br>` +
      `Oversees: ${esc(r.c.sectors.join(", "))}`;
    const name = COMMITTEE_SHORT[r.c.id] || r.c.name;
    body += `<g class="row" data-tip="${esc(tipHtml)}">
      <rect class="row-bg" x="0" y="${cy - rowH / 2}" width="${w}" height="${rowH}" rx="3"/>
      <text class="num" x="0" y="${cy + 4}">${r.c.chamber[0]}</text>
      <text class="lbl" x="16" y="${cy + 4}">${esc(name)}</text>
      <line class="dumb-line ${up ? "up" : ""}" x1="${x(r.expected)}" x2="${x(r.observed)}" y1="${cy}" y2="${cy}"/>
      <circle class="dot-exp" cx="${x(r.expected)}" cy="${cy}" r="5"/>
      <circle class="dot-obs" cx="${x(r.observed)}" cy="${cy}" r="6"/>
      <text class="num" x="${x(Math.max(r.observed, r.expected)) + 12}" y="${cy + 4}">${Math.round(r.observed * 100)}%</text>
    </g>`;
  });
  el.innerHTML = svgWrap(w, h, g + body, "Observed versus expected overlap share by committee");
}

function drawMonthlyChart(el, trades, minH = 236) {
  const w = Math.max(300, el.clientWidth);
  const h = Math.max(236, minH), top = 14, bottom = 26, left = 34, right = 6;

  const start = state.year === "all" ? DATA.meta.coverage_start.slice(0, 7) : `${state.year}-01`;
  const endYear = state.year === "all" ? DATA.meta.as_of.slice(0, 7) : `${state.year}-12`;
  const end = endYear > DATA.meta.as_of.slice(0, 7) ? DATA.meta.as_of.slice(0, 7) : endYear;
  const months = [];
  let [y, m] = start.split("-").map(Number);
  while (`${y}-${String(m).padStart(2, "0")}` <= end) {
    months.push(`${y}-${String(m).padStart(2, "0")}`);
    m++; if (m > 12) { m = 1; y++; }
  }
  const buckets = new Map(months.map((k) => [k, { buy: 0, sell: 0, exchange: 0 }]));
  for (const t of trades) {
    const b = buckets.get(t.trade_date.slice(0, 7));
    if (b) b[t.type]++;
  }
  const maxV = Math.max(1, ...[...buckets.values()].map((b) => b.buy + b.sell));
  const step = maxV > 120 ? 40 : maxV > 60 ? 20 : maxV > 24 ? 10 : 5;
  const ymax = niceMax(maxV, step);
  const ih = h - top - bottom, iw = w - left - right;
  const yv = (v) => top + ih - (v / ymax) * ih;
  const slot = iw / months.length;
  const bw = Math.max(2, Math.min(22, slot - 2));

  let g = `<g class="grid">`;
  for (let v = 0; v <= ymax; v += step) {
    g += `<line x1="${left}" x2="${w - right}" y1="${yv(v)}" y2="${yv(v)}"/>`;
    g += `<text x="${left - 8}" y="${yv(v) + 4}" text-anchor="end">${v}</text>`;
  }
  g += `</g>`;

  let cols = "";
  months.forEach((k, i) => {
    const b = buckets.get(k);
    const x0 = left + i * slot + (slot - bw) / 2;
    const yBuy = yv(b.buy), ySell = yv(b.buy + b.sell);
    const gap = b.buy && b.sell ? 2 : 0;
    const tipHtml = `<b>${fmtMonth(`${k}-01`)}</b><br>Purchases <span class="tip-mono">${b.buy}</span><br>Sales <span class="tip-mono">${b.sell}</span>` +
      (b.exchange ? `<br>Exchanges <span class="tip-mono">${b.exchange}</span> (not drawn)` : "");
    cols += `<g class="col" data-tip="${esc(tipHtml)}">
      <rect class="hit" x="${left + i * slot}" y="${top}" width="${slot}" height="${ih}"/>
      ${b.buy ? `<rect class="bar-buy" x="${x0}" y="${yBuy}" width="${bw}" height="${yv(0) - yBuy}" rx="1.5"/>` : ""}
      ${b.sell ? `<rect class="bar-sell" x="${x0}" y="${ySell}" width="${bw}" height="${Math.max(0, yBuy - ySell - gap)}" rx="1.5"/>` : ""}
    </g>`;
    const [yy, mm] = k.split("-");
    const showLabel = months.length <= 14 ? (mm === "01" || mm === "04" || mm === "07" || mm === "10") : (mm === "01" || mm === "07");
    if (showLabel) {
      const lbl = new Date(`${k}-01T00:00:00Z`).toLocaleDateString("en-US", { month: "short", timeZone: "UTC" });
      cols += `<text x="${x0 + bw / 2}" y="${h - 8}" text-anchor="middle">${lbl} ’${yy.slice(2)}</text>`;
    }
  });
  const axis = `<line class="axis" x1="${left}" x2="${w - right}" y1="${yv(0)}" y2="${yv(0)}"/>`;
  let busiest = months[0];
  for (const k of months) {
    const b = buckets.get(k), c = buckets.get(busiest);
    if (b.buy + b.sell > c.buy + c.sell) busiest = k;
  }
  const tb = trades.filter((t) => t.type === "buy").length, tsell = trades.filter((t) => t.type === "sell").length;
  const bb = buckets.get(busiest);
  el.innerHTML = svgWrap(w, h, g + cols + axis, "Disclosed trades by month, purchases and sales") +
    `<p class="chart-foot"><span><b>${fmtInt(tb)}</b>purchases</span><span><b>${fmtInt(tsell)}</b>sales</span>` +
    `<span><b>${fmtMonth(`${busiest}-01`)}</b>busiest month, ${bb.buy + bb.sell} trades</span></p>`;
}

function drawLagChart(el, trades) {
  const w = Math.max(300, el.clientWidth);
  const h = window.innerWidth >= 900 ? 400 : 260, top = 28, bottom = 28, left = 38, right = 8;
  const binW = 5, cap = 180;
  const nb = cap / binW + 1;
  const bins = new Array(nb).fill(0);
  for (const t of trades) bins[Math.min(nb - 1, Math.floor((t.days_to_file - 1) / binW))]++;
  const maxV = Math.max(1, ...bins);
  const step = maxV > 200 ? 100 : maxV > 80 ? 40 : maxV > 30 ? 10 : 5;
  const ymax = niceMax(maxV, step);
  const ih = h - top - bottom, iw = w - left - right;
  const slot = iw / nb;
  const bw = Math.max(1.5, slot - 2);
  const yv = (v) => top + ih - (v / ymax) * ih;
  const xd = (days) => left + (days / binW) * slot;

  let g = `<g class="grid">`;
  for (let v = 0; v <= ymax; v += step) {
    g += `<line x1="${left}" x2="${w - right}" y1="${yv(v)}" y2="${yv(v)}"/>`;
    g += `<text x="${left - 8}" y="${yv(v) + 4}" text-anchor="end">${v}</text>`;
  }
  g += `</g>`;

  let bars = "";
  bins.forEach((n, i) => {
    const lo = i * binW + 1, hi = (i + 1) * binW;
    const late = lo > DEADLINE_DAYS;
    const label = i === nb - 1 ? `More than ${cap} days` : `${lo}–${hi} days`;
    const tipHtml = `<b>${label}</b><br><span class="tip-mono">${fmtInt(n)}</span> trades${late ? " · past the deadline" : ""}`;
    bars += `<g class="col" data-tip="${esc(tipHtml)}">
      <rect class="hit" x="${left + i * slot}" y="${top}" width="${slot}" height="${ih}"/>
      ${n ? `<rect class="${late ? "bar-late" : "bar-ok"}" x="${left + i * slot + 1}" y="${yv(n)}" width="${bw}" height="${yv(0) - yv(n)}" rx="1.5"/>` : ""}
    </g>`;
  });

  let ticks = "";
  for (const d of [0, 30, 60, 90, 120, 150]) {
    ticks += `<text x="${xd(d)}" y="${h - 8}" text-anchor="middle">${d}</text>`;
  }
  ticks += `<text x="${left + (nb - 0.5) * slot}" y="${h - 8}" text-anchor="middle">${cap}+</text>`;
  const dx = xd(DEADLINE_DAYS);
  const deadline = `<line class="deadline" x1="${dx}" x2="${dx}" y1="${top - 14}" y2="${yv(0)}"/>
    <text class="deadline-lbl" x="${dx + 6}" y="${top - 4}">45-day deadline</text>`;
  const axis = `<line class="axis" x1="${left}" x2="${w - right}" y1="${yv(0)}" y2="${yv(0)}"/>`;
  const lags = trades.map((t) => t.days_to_file);
  const within = trades.filter((t) => t.days_to_file <= DEADLINE_DAYS).length;
  el.innerHTML = svgWrap(w, h, g + bars + axis + deadline + ticks, "Histogram of days from trade to disclosure") +
    (trades.length ? `<p class="chart-foot"><span><b>${Math.round(median(lags))} days</b>median wait</span>` +
    `<span><b>${fmtPct(within / trades.length, 1)}</b>filed on time</span>` +
    `<span><b>${Math.max(...lags)} days</b>longest wait</span></p>` : "");
}

/* ---------------- tables ---------------- */

const TRADE_HEAD = `<thead><tr>
  <th>Filed</th><th>Member</th><th>Security</th><th>Type</th><th>Amount</th>
  <th>Traded</th><th>Lag</th><th>Committee overlap</th><th class="num" title="Return minus SPY, 30 days after the trade">30d vs SPY</th>
</tr></thead>`;

function tradeRow(t) {
  const m = memberById.get(t.member_id);
  return `<tr>
    <td class="mono">${t.filed_date}</td>
    <td><div class="who"><button type="button" class="linkbtn who-name" data-member="${m.id}">${esc(m.name)}</button>${partyTag(m)}</div></td>
    <td><div class="sec"><span class="ticker">${esc(t.ticker)}</span><span class="company" title="${esc(t.company)}">${esc(t.company)}</span></div></td>
    <td><span class="ttype ttype-${t.type}">${TYPE_LABEL[t.type]}</span><div class="muted" style="font-size:.75rem">${esc(t.owner)}</div></td>
    <td><span class="band" title="Disclosed band ${t.amount_band + 1} of 10">${bandMeter(t.amount_band)}<span class="band-text">${bandLabel(t)}</span></span></td>
    <td class="mono muted">${t.trade_date}</td>
    <td>${lagCell(t)}</td>
    <td>${t.overlap_committee ? `<span class="ovl" title="${esc(committeeLabel(t.overlap_committee))} oversees ${esc(t.sector)}">${esc(COMMITTEE_SHORT[t.overlap_committee])}</span>` : `<span class="muted" style="font-size:.75rem">${esc(t.sector)}</span>`}</td>
    <td class="num">${retCell(t.excess_return_30d)}</td>
  </tr>`;
}

function tradeTable(el, rows, emptyText = "No trades match these filters.") {
  el.innerHTML = TRADE_HEAD + `<tbody>${rows.length ? rows.map(tradeRow).join("") : `<tr><td class="empty" colspan="9">${emptyText}</td></tr>`}</tbody>`;
}

/* ---------------- views ---------------- */

function renderOverview() {
  const trades = filteredTrades();
  const stats = overlapStats(trades);
  const late = trades.filter((t) => t.days_to_file > DEADLINE_DAYS).length;
  const traders = new Set(trades.map((t) => t.member_id));
  const vr = valueRange(trades);

  const period = state.year === "all"
    ? `${fmtMonth(DATA.meta.coverage_start)} – ${fmtMonth(DATA.meta.as_of)}`
    : `Trades made in ${state.year}`;
  const scope = state.chamber === "all" ? "House and Senate" : state.chamber;
  $("#ov-eyebrow").textContent = `${period} · ${scope}${state.party !== "all" ? ` · ${PARTY_NAME[state.party]}s` : ""}`;

  if (!trades.length) {
    $("#ov-headline").textContent = "No disclosed trades in this selection.";
    $("#ov-sub").textContent = "Widen the year, chamber or party filter above.";
  } else {
    $("#ov-headline").innerHTML =
      `<span class="hl">${fmtPct(stats.observed)}</span> of disclosed stock trades were in an industry the member’s own committee oversees.`;
    $("#ov-sub").textContent =
      `If each member had traded like Congress as a whole, that share would be about ${fmtPct(stats.expected)}. ` +
      `The gap is a pattern to examine. It does not show that anyone used inside information.`;
  }

  $("#ov-kpis").innerHTML = `
    <div><dt>Trades disclosed</dt><dd>${fmtInt(trades.length)}<small>${fmtInt(stats.count)} in overseen industries</small></dd></div>
    <div><dt>Members trading</dt><dd>${traders.size}<small>of ${filteredMembers().length} in the data</small></dd></div>
    <div><dt>Disclosed value</dt><dd>${vr.text}<small>Sum of band floors to ceilings</small></dd></div>
    <div><dt>Filed late</dt><dd>${trades.length ? fmtPct(late / trades.length, 1) : "–"}<small>${fmtInt(late)} trades past 45 days</small></dd></div>`;

  drawCommitteeChart($("#ch-committee"), trades);
  const wide = window.innerWidth >= 900;
  const cH = $("#ch-committee svg")?.getAttribute("height") || 0;
  drawMonthlyChart($("#ch-monthly"), trades, wide ? Number(cH) - 64 : 236);
  tradeTable($("#ov-latest"), trades.slice(0, 8));
}

function renderTrades() {
  const f = state.trades;
  const q = f.q.trim().toLowerCase();
  const all = filteredTrades().filter((t) => {
    if (f.type && t.type !== f.type) return false;
    if (f.sector && t.sector !== f.sector) return false;
    if (f.overlap && !t.overlap_committee) return false;
    if (f.late && t.days_to_file <= DEADLINE_DAYS) return false;
    if (q) {
      const m = memberById.get(t.member_id);
      if (!(`${m.name} ${t.ticker} ${t.company}`.toLowerCase().includes(q))) return false;
    }
    return true;
  });
  $("#tr-count").textContent = `${fmtInt(all.length)} transactions, newest filing first.`;
  tradeTable($("#tr-table"), all.slice(0, f.limit));
  $("#tr-more").hidden = all.length <= f.limit;
}

const MEMBER_COLS = [
  { key: "name", label: "Member", sort: (r) => r.m.name, dir: 1 },
  { key: "comms", label: "Committees" },
  { key: "trades", label: "Trades", num: true, sort: (r) => r.n },
  { key: "overlap", label: "Overlap", num: true, sort: (r) => r.overlap },
  { key: "late", label: "Filed late", num: true, sort: (r) => r.late },
  { key: "med", label: "Median days", num: true, sort: (r) => r.medLag },
  { key: "value", label: "Disclosed value", num: true, sort: (r) => r.mid },
];

function renderMembers() {
  const rows = memberRollup(filteredTrades());
  const col = MEMBER_COLS.find((c) => c.key === state.members.sort);
  const dir = state.members.dir;
  rows.sort((a, b) => {
    const va = col.sort(a), vb = col.sort(b);
    return (va > vb ? 1 : va < vb ? -1 : 0) * dir;
  });
  const head = `<thead><tr>${MEMBER_COLS.map((c) => {
    const sorted = c.key === state.members.sort;
    const aria = sorted ? ` aria-sort="${dir > 0 ? "ascending" : "descending"}"` : "";
    const arrow = sorted ? (dir > 0 ? " ↑" : " ↓") : "";
    return `<th class="${c.num ? "num" : ""}"${aria}>${c.sort ? `<button type="button" data-sort="${c.key}">${c.label}${arrow}</button>` : c.label}</th>`;
  }).join("")}</tr></thead>`;
  const body = rows.map((r) => `<tr data-member="${r.m.id}" tabindex="0">
    <td><div class="who"><span class="who-name">${esc(r.m.name)}</span>${partyTag(r.m)}</div></td>
    <td><div class="comm-codes">${r.m.committees.map((id) => `<span title="${esc(committeeLabel(id))}">${esc(COMMITTEE_SHORT[id])}</span>`).join("")}</div></td>
    <td class="num mono">${r.n}</td>
    <td class="num"><span class="minibar"><span class="mono">${fmtPct(r.overlap)}</span><span class="minibar-track"><span class="minibar-fill" style="width:${(r.overlap * 100).toFixed(1)}%"></span></span></span></td>
    <td class="num">${r.late ? `<span class="lag-late">${r.late}</span>` : `<span class="mono muted">0</span>`}</td>
    <td class="num mono">${Math.round(r.medLag)}</td>
    <td class="num mono">${r.value.text}</td>
  </tr>`).join("");
  $("#mb-table").innerHTML = head + `<tbody>${body || `<tr><td class="empty" colspan="7">No members traded in this selection.</td></tr>`}</tbody>`;
}

function renderFilings() {
  const trades = filteredTrades();
  const late = trades.filter((t) => t.days_to_file > DEADLINE_DAYS);
  const share = trades.length ? late.length / trades.length : 0;
  $("#lf-headline").innerHTML = share > 0
    ? `<span class="hl-late">1 in ${Math.round(1 / share)}</span> trades was disclosed after the 45-day deadline.`
    : "No trades in this selection were disclosed late.";
  drawLagChart($("#ch-lag"), trades);

  const rows = memberRollup(trades).filter((r) => r.late > 0)
    .sort((a, b) => b.late - a.late || b.maxLag - a.maxLag).slice(0, 10);
  $("#lf-rank").innerHTML = rows.map((r) => `<li data-member="${r.m.id}" tabindex="0">
      <div class="who"><span class="who-name">${esc(r.m.name)}</span>${partyTag(r.m)}</div>
      <span class="rank-n">${r.late} late</span>
      <span class="rank-detail">Longest wait ${r.maxLag} days · ${fmtPct(r.late / r.n)} of their ${r.n} trades</span>
    </li>`).join("") || `<li class="muted">None.</li>`;
}

function renderMichigan() {
  const all = filteredTrades();
  const mi = all.filter((t) => memberById.get(t.member_id).state === "MI");
  const rest = all.filter((t) => memberById.get(t.member_id).state !== "MI");
  const miStats = overlapStats(mi, all), restStats = overlapStats(rest, all);
  const lateShare = (ts) => (ts.length ? ts.filter((t) => t.days_to_file > DEADLINE_DAYS).length / ts.length : 0);
  const delegation = filteredMembers().filter((m) => m.state === "MI");
  const rollup = new Map(memberRollup(mi).map((r) => [r.m.id, r]));

  $("#mi-sub").textContent =
    `${delegation.length} seats in this selection, ${rollup.size} with disclosed trades. ` +
    `The comparison column is every other member of Congress under the same filters.`;
  $("#mi-kpis").innerHTML = `
    <div><dt>Overlap share</dt><dd>${mi.length ? fmtPct(miStats.observed) : "–"}<small>rest of Congress ${fmtPct(restStats.observed)}</small></dd></div>
    <div><dt>Filed late</dt><dd>${mi.length ? fmtPct(lateShare(mi)) : "–"}<small>rest of Congress ${fmtPct(lateShare(rest))}</small></dd></div>
    <div><dt>Trades disclosed</dt><dd>${fmtInt(mi.length)}<small>${valueRange(mi).text}</small></dd></div>
    <div><dt>Median days to file</dt><dd>${mi.length ? Math.round(median(mi.map((t) => t.days_to_file))) : "–"}<small>rest of Congress ${Math.round(median(rest.map((t) => t.days_to_file)) || 0)}</small></dd></div>`;

  const order = (m) => (m.chamber === "Senate" ? 100 : 0) + (m.district || 0);
  $("#mi-grid").innerHTML = delegation.sort((a, b) => order(a) - order(b)).map((m) => {
    const r = rollup.get(m.id);
    const seatLabel = m.chamber === "House" ? `District ${m.district}` : "Senate";
    return `<button type="button" class="mi-card ${r ? "" : "quiet"}" data-member="${m.id}">
      <span class="mi-top"><span class="mi-seat">${seatLabel.toUpperCase()}</span><span class="tag"><i class="pdot p-${m.party}"></i>${m.party}</span></span>
      <span class="mi-name">${esc(m.name)}</span>
      ${r ? `<span class="mi-stats"><span><b>${r.n}</b>trades</span><span><b>${fmtPct(r.overlap)}</b>overlap</span><span><b>${r.late}</b>late</span></span>`
          : `<span class="mi-none">No trades disclosed</span>`}
    </button>`;
  }).join("");

  tradeTable($("#mi-table"), mi.slice(0, state.mi.limit), "No Michigan trades in this selection.");
  $("#mi-more").hidden = mi.length <= state.mi.limit;
}

function renderMethod() {
  const bands = DATA.meta.amount_bands;
  $("#band-legend").innerHTML = bands.map((b, i) => {
    const text = b.max == null ? `Over $${fmtInt(b.min - 1)}` : `$${fmtInt(b.min)} – $${fmtInt(b.max)}`;
    return `<span class="band">${bandMeter(i)}<span class="band-text">${text}</span></span>`;
  }).join("");
  const p = DATA.meta.pipeline;
  $("#health").innerHTML = `
    <div><dt>Filings downloaded</dt><dd>${fmtInt(p.filings_downloaded)}</dd></div>
    <div><dt>Filings parsed</dt><dd>${fmtInt(p.filings_parsed)}</dd></div>
    <div><dt>Scanned, awaiting review</dt><dd>${fmtInt(p.scanned_needing_review)}</dd></div>
    <div><dt>Amendments applied</dt><dd>${fmtInt(p.amendments_superseded)}</dd></div>
    <div><dt>Unmatched tickers</dt><dd>${fmtInt(p.tickers_unmatched)}</dd></div>
    <div><dt>Row reconciliation</dt><dd class="${p.rows_reconciled ? "health-ok" : "ret-neg"}">${p.rows_reconciled ? "Passed" : "Failed"}</dd></div>
    <div><dt>Trades in this data</dt><dd>${fmtInt(DATA.trades.length)}</dd></div>`;
}

/* ---------------- member drawer ---------------- */

let lastFocus = null;
function openMember(id) {
  const m = memberById.get(id);
  if (!m) return;
  const ts = filteredTrades().filter((t) => t.member_id === id);
  const overseen = overseenSectors(m);
  const sectorCounts = new Map();
  for (const t of ts) sectorCounts.set(t.sector, (sectorCounts.get(t.sector) || 0) + 1);
  const secRows = [...sectorCounts].sort((a, b) => b[1] - a[1]);
  const maxS = Math.max(1, ...secRows.map((r) => r[1]));
  const late = ts.filter((t) => t.days_to_file > DEADLINE_DAYS).length;
  const ov = ts.filter((t) => t.overlap_committee).length;

  $("#drawer-body").innerHTML = `
    <p class="dr-seat"><i class="pdot p-${m.party}"></i>${PARTY_NAME[m.party]} · ${esc(m.chamber)} · ${esc(seat(m))}</p>
    <h2 class="dr-name" id="dr-name">${esc(m.name)}</h2>
    <dl class="dr-stats">
      <div><dt>Trades</dt><dd>${ts.length}</dd></div>
      <div><dt>Overlap</dt><dd>${ts.length ? fmtPct(ov / ts.length) : "–"}</dd></div>
      <div><dt>Filed late</dt><dd>${late}</dd></div>
      <div><dt>Median days</dt><dd>${ts.length ? Math.round(median(ts.map((t) => t.days_to_file))) : "–"}</dd></div>
    </dl>
    <h3 class="dr-h">Committees</h3>
    <ul class="dr-comms">${m.committees.map((cid) => {
      const c = committeeById.get(cid);
      return `<li>${esc(c.chamber)} ${esc(c.name)}<span>Oversees ${esc(c.sectors.join(", "))}</span></li>`;
    }).join("")}</ul>
    <h3 class="dr-h">Trades by industry</h3>
    ${secRows.length ? `<div class="secbars">${secRows.map(([s, n]) => `
      <div class="secbar ${overseen.has(s) ? "ov" : ""}">
        <span class="secbar-name" title="${esc(s)}">${esc(s)}</span>
        <span class="secbar-track"><span class="secbar-fill" style="display:block;width:${(n / maxS) * 100}%"></span></span>
        <span class="secbar-n">${n}</span>
      </div>`).join("")}</div>
      <p class="dr-note">Highlighted industries fall under this member’s committees.</p>` : `<p class="muted">No trades in this selection.</p>`}
    <h3 class="dr-h">Recent trades</h3>
    <div class="dr-trades">${ts.slice(0, 12).map((t) => `
      <div class="dr-trade">
        <span><span class="ticker">${esc(t.ticker)}</span> <span class="ttype ttype-${t.type}" style="margin-left:6px">${TYPE_LABEL[t.type]}</span></span>
        <span class="band-text">${bandLabel(t)}</span>
        <span class="r2"><span class="mono">${t.trade_date}</span>${lagCell(t)}${t.overlap_committee ? `<span class="ovl">${esc(COMMITTEE_SHORT[t.overlap_committee])}</span>` : ""}</span>
      </div>`).join("")}</div>`;

  lastFocus = document.activeElement;
  $("#scrim").hidden = false;
  $("#drawer").hidden = false;
  $("#drawer").scrollTop = 0;
  $("#drawer-close").focus();
}
function closeMember() {
  $("#scrim").hidden = true;
  $("#drawer").hidden = true;
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}

/* ---------------- theme ---------------- */

// Auto follows the device setting; Light and Dark override it via data-theme,
// which styles.css already handles. The choice is remembered per browser.
const THEMES = ["auto", "light", "dark"];
const THEME_LABEL = { auto: "Auto", light: "Light", dark: "Dark" };

function currentTheme() {
  return document.documentElement.getAttribute("data-theme") || "auto";
}
function applyTheme(t) {
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
  try { localStorage.setItem("overlap-theme", t); } catch (e) { /* storage blocked: still works for this visit */ }
  $("#theme-label").textContent = THEME_LABEL[t];
  $("#theme-btn").setAttribute("aria-label", `Color theme: ${THEME_LABEL[t]}. Select to change.`);
}
function setupTheme() {
  applyTheme(currentTheme());
  $("#theme-btn").addEventListener("click", () => {
    applyTheme(THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length]);
  });
}

/* ---------------- routing + controls ---------------- */

const VIEWS = ["overview", "trades", "members", "filings", "michigan", "method"];
const RENDER = {
  overview: renderOverview, trades: renderTrades, members: renderMembers,
  filings: renderFilings, michigan: renderMichigan, method: renderMethod,
};

function route() {
  const h = location.hash.replace("#", "");
  state.view = VIEWS.includes(h) ? h : "overview";
  for (const v of VIEWS) $(`#view-${v}`).hidden = v !== state.view;
  document.querySelectorAll(".tabs a").forEach((a) => {
    if (a.dataset.view === state.view) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  RENDER[state.view]();
}

function segmented(el, key, options) {
  el.innerHTML = options.map(([v, label]) =>
    `<button type="button" data-v="${v}" aria-pressed="${state[key] === v}">${label}</button>`).join("");
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state[key] = b.dataset.v;
    el.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    state.trades.limit = 50;
    state.mi.limit = 50;
    RENDER[state.view]();
  });
}

function setup() {
  const years = [...new Set(DATA.trades.map((t) => t.trade_date.slice(0, 4)))].sort();
  segmented($("#f-year"), "year", [["all", "All years"], ...years.map((y) => [y, y])]);
  segmented($("#f-chamber"), "chamber", [["all", "Both chambers"], ["House", "House"], ["Senate", "Senate"]]);
  segmented($("#f-party"), "party", [["all", "All parties"], ["D", "Democrats"], ["R", "Republicans"], ["I", "Independents"]]);

  const asof = `Filings through ${fmtLongDate(DATA.meta.as_of)}`;
  $("#asof").textContent = asof;
  $("#foot-asof").textContent = asof;
  $("#sample-band").hidden = !DATA.meta.sample;

  const sectors = [...new Set(DATA.trades.map((t) => t.sector))].sort();
  $("#tr-sector").insertAdjacentHTML("beforeend", sectors.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join(""));

  const tf = state.trades;
  const onTradeFilter = () => { tf.limit = 50; renderTrades(); };
  $("#tr-q").addEventListener("input", (e) => { tf.q = e.target.value; onTradeFilter(); });
  $("#tr-type").addEventListener("change", (e) => { tf.type = e.target.value; onTradeFilter(); });
  $("#tr-sector").addEventListener("change", (e) => { tf.sector = e.target.value; onTradeFilter(); });
  $("#tr-overlap").addEventListener("change", (e) => { tf.overlap = e.target.checked; onTradeFilter(); });
  $("#tr-late").addEventListener("change", (e) => { tf.late = e.target.checked; onTradeFilter(); });
  $("#tr-more").addEventListener("click", () => { tf.limit += 50; renderTrades(); });
  $("#mi-more").addEventListener("click", () => { state.mi.limit += 50; renderMichigan(); });

  $("#mb-table").addEventListener("click", (e) => {
    const s = e.target.closest("[data-sort]");
    if (!s) return;
    e.stopPropagation();
    const key = s.dataset.sort;
    if (state.members.sort === key) state.members.dir *= -1;
    else { state.members.sort = key; state.members.dir = MEMBER_COLS.find((c) => c.key === key).dir || -1; }
    renderMembers();
  });

  // Any element carrying data-member opens that member's profile.
  const main = $("#main");
  main.addEventListener("click", (e) => {
    if (e.target.closest("[data-sort]")) return;
    const el = e.target.closest("[data-member]");
    if (el) openMember(el.dataset.member);
  });
  main.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const el = e.target.closest("tr[data-member], li[data-member]");
    if (el) { e.preventDefault(); openMember(el.dataset.member); }
  });
  $("#drawer-close").addEventListener("click", closeMember);
  $("#scrim").addEventListener("click", closeMember);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#drawer").hidden) closeMember(); });

  bindTips(main);
  window.addEventListener("hashchange", route);
  window.addEventListener("scroll", () => { tip().hidden = true; }, { passive: true });

  let lastW = window.innerWidth, timer = null;
  window.addEventListener("resize", () => {
    if (window.innerWidth === lastW) return;
    lastW = window.innerWidth;
    clearTimeout(timer);
    timer = setTimeout(() => { if (["overview", "filings"].includes(state.view)) RENDER[state.view](); }, 120);
  });
}

async function boot() {
  setupTheme();
  try {
    const res = await fetch(DATA_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    DATA = await res.json();
  } catch (err) {
    $("#loading").textContent =
      `Couldn't load ${DATA_URL} (${err.message}). If you opened this file directly, serve the folder instead: python -m http.server -d frontend`;
    return;
  }
  DATA.members.forEach((m) => memberById.set(m.id, m));
  DATA.committees.forEach((c) => committeeById.set(c.id, c));
  $("#loading").hidden = true;
  setup();
  route();
}

boot();
