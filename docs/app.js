/* Central Bank Monitor — renders docs/data/*.json. All times are SGT strings
   produced by the pipeline (no browser time-zone conversion). */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const S = { meta: null, banks: {}, order: [], spec: {}, cal: {}, feed: {}, feedMonths: [], calBank: "ALL", feedBank: "ALL",
              specBank: "FED", month: null, sel: null, feedShown: 50, listView: false };

  const pref = (k, v) => { try { if (v === undefined) return localStorage.getItem("cbm-" + k); localStorage.setItem("cbm-" + k, v); } catch (e) { return null; } };
  const getJSON = async url => { const r = await fetch(url, { cache: "no-cache" }); if (!r.ok) throw new Error(url + " " + r.status); return r.json(); };
  const fmtDate = iso => { const [y, m, d] = iso.split("-").map(Number); return `${d} ${MON[m - 1]} ${y}`; };
  const short = code => (S.banks[code] || {}).short || code;
  const dir = mv => mv == null ? null : mv > 0 ? "hike" : mv < 0 ? "cut" : "hold";
  const glyph = { hike: "▲", cut: "▼", hold: "■" };

  /* ---------- bank selectors ---------- */
  function segment(el, withAll, current, onPick) {
    const codes = (withAll ? ["ALL"] : []).concat(S.order);
    el.innerHTML = codes.map(c => `<button role="tab" data-c="${c}" aria-selected="${c === current}">${c === "ALL" ? "All" : esc(short(c))}</button>`).join("");
    el.onclick = e => { const b = e.target.closest("button"); if (!b) return; el.querySelectorAll("button").forEach(x => x.setAttribute("aria-selected", x === b)); onPick(b.dataset.c); };
  }

  /* ---------- header & stale sources ---------- */
  function renderHeader() {
    const m = S.meta, u = m.updated;
    const ageH = (Date.now() - Date.parse(u)) / 36e5;
    const [, um, ud] = u.slice(0, 10).split("-").map(Number);
    $("#updated").textContent = `Updated ${ud} ${MON[um - 1]} ${u.slice(11, 16)} SGT` + (ageH > 30 ? " · overdue" : "");
    $("#updated").title = `Last refresh ${fmtDate(u.slice(0, 10))} ${u.slice(11, 16)} SGT`;
    const stale = m.stale || [];
    const notes = S.order.map(c => S.banks[c]).filter(b => b.access_note);
    const btn = $("#staleBtn"), panel = $("#stalePanel");
    btn.hidden = false;
    btn.textContent = stale.length ? `${stale.length} source${stale.length > 1 ? "s" : ""} stale` : "Sources";
    if (!stale.length) { btn.style.borderColor = "var(--line-2)"; btn.style.color = "var(--ink-2)"; btn.style.background = "var(--panel-2)"; }
    const label = sid => { const [b, ...rest] = sid.split(":"); return (S.banks[b] ? short(b) + " · " : b + " · ") + rest.join(":").replace(/-/g, " "); };
    panel.innerHTML =
      (stale.length ? `<h3>Failed on the latest run</h3><ul>${stale.map(s => `<li>${esc(label(s.source))} <span class="muted">· last OK ${s.last_ok ? esc(s.last_ok.slice(0, 16).replace("T", " ")) : "never"}</span></li>`).join("")}</ul>`
                    : `<h3>Latest run</h3><p class="muted" style="margin:0 0 10px">All sources refreshed.</p>`) +
      `<h3>Known access limits</h3><ul>${notes.map(b => `<li><b>${esc(b.short)}</b> · ${esc(b.access_note)}</li>`).join("")}</ul>` +
      (m.ai && !m.ai.enabled ? `<h3>AI step</h3><p class="muted" style="margin:0">Not run: speech paraphrases, translations, stances and expectations were not updated.</p>` : "");
    btn.onclick = () => { const open = panel.hidden; panel.hidden = !open; btn.setAttribute("aria-expanded", open); };
    document.addEventListener("click", e => { if (!panel.hidden && !panel.contains(e.target) && e.target !== btn) { panel.hidden = true; btn.setAttribute("aria-expanded", "false"); } });
  }

  /* ---------- calendar ---------- */
  async function loadMonth(key) {
    if (S.cal[key] !== undefined) return S.cal[key];
    if (!S.meta.months.calendar.includes(key)) return (S.cal[key] = null);
    try { S.cal[key] = (await getJSON(`data/calendar/${key}.json`)).events; } catch (e) { S.cal[key] = null; }
    return S.cal[key];
  }
  const shiftMonth = (key, n) => { let [y, m] = key.split("-").map(Number); m += n; while (m > 12) { m -= 12; y++; } while (m < 1) { m += 12; y--; } return `${y}-${String(m).padStart(2, "0")}`; };

  function evResult(ev) {
    if (ev.type === "speech") return { cls: "spk", g: "◦", txt: ev.title.replace(/^(\w+ )?(\w+\.? )?/, "") };
    if (ev.decision) {
      const d = dir(ev.decision.move);
      const txt = ev.bank === "MAS" ? (ev.decision.move === 0 ? "Unch." : ev.decision.move > 0 ? "Tighten" : "Ease")
                : d === "hold" ? "Hold" : `${ev.decision.move > 0 ? "+" : ""}${ev.decision.move}`;
      return { cls: d, g: glyph[d], txt };
    }
    if (ev.expected) return { cls: "exp", g: "E", txt: ev.expected.move === 0 ? "Hold" : `${ev.expected.move > 0 ? "+" : ""}${ev.expected.move}` };
    return { cls: "exp", g: "E", txt: ev.status === "awaiting" ? "Pending" : "TBC" };
  }

  async function renderCalendar() {
    const key = S.month, [y, m] = key.split("-").map(Number);
    $("#monthLabel").textContent = `${MON[m - 1]} ${y}`;
    const events = (await loadMonth(key)) || [];
    const vis = events.filter(e => S.calBank === "ALL" || e.bank === S.calBank);
    const byDay = {};
    vis.forEach(e => (byDay[e.date] = byDay[e.date] || []).push(e));
    const first = new Date(Date.UTC(y, m - 1, 1)), lead = (first.getUTCDay() + 6) % 7, days = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const cells = [];
    for (let i = 0; i < lead; i++) cells.push(`<div class="day out" aria-hidden="true"></div>`);
    for (let d = 1; d <= days; d++) {
      const iso = `${key}-${String(d).padStart(2, "0")}`, list = byDay[iso] || [];
      const wd = (lead + d - 1) % 7;
      const meet = list.filter(e => e.type !== "speech"), spk = list.filter(e => e.type === "speech");
      const lines = meet.concat(spk);
      const shown = lines.slice(0, 4).map(e => {
        const r = evResult(e);
        return `<div class="ev ${e.type === "speech" ? "speech" : ""}"><i class="g ${r.cls}">${r.g}</i><span class="code">${esc(short(e.bank))}</span>${e.time ? `<span class="t">${e.time}</span>` : ""}<span class="r">${esc(r.txt)}</span></div>`;
      }).join("");
      const dots = lines.slice(0, 6).map(e => `<i class="${e.type === "speech" ? "spk" : (evResult(e).cls)}"></i>`).join("");
      const label = `${d} ${FULL[m - 1]}: ${meet.length} meeting${meet.length !== 1 ? "s" : ""}, ${spk.length} speech${spk.length !== 1 ? "es" : ""}`;
      cells.push(`<button class="day${wd > 4 ? " wkend" : ""}${iso === S.meta.today ? " today" : ""}${iso === S.sel ? " sel" : ""}" data-d="${iso}" aria-label="${label}">` +
                 `<span class="dn">${d}</span>${shown}${lines.length > 4 ? `<span class="more">+${lines.length - 4} more</span>` : ""}<span class="dots">${dots}</span></button>`);
    }
    while (cells.length % 7) cells.push(`<div class="day out" aria-hidden="true"></div>`);
    const grid = $("#calGrid");
    grid.innerHTML = events.length || S.meta.months.calendar.includes(key) ? cells.join("") : cells.join("");
    grid.onclick = e => { const b = e.target.closest("button.day"); if (!b) return; S.sel = b.dataset.d; grid.querySelectorAll(".day.sel").forEach(x => x.classList.remove("sel")); b.classList.add("sel"); renderDetail(byDay); };
    if (!S.sel || S.sel.slice(0, 7) !== key) {
      const firstWith = Object.keys(byDay).sort()[0];
      S.sel = S.meta.today.slice(0, 7) === key ? S.meta.today : (firstWith || `${key}-01`);
      const b = grid.querySelector(`[data-d="${S.sel}"]`); if (b) b.classList.add("sel");
    }
    renderDetail(byDay, !S.meta.months.calendar.includes(key));
  }

  function srcPill(k) { return k ? `<span class="pill">${k === "official" ? "Official" : k === "BIS" ? "BIS data" : k === "wire" ? "Wire report" : esc(k)}</span>` : ""; }

  function card(ev) {
    const b = S.banks[ev.bank] || {};
    const when = ev.time ? `${ev.time} SGT` + (ev.local_date && ev.local_date !== ev.date ? ` · ${fmtDate(ev.local_date)} local` : "") : (ev.type === "speech" ? "" : "Time TBC");
    if (ev.type === "speech") {
      return `<div class="card"><div class="row1"><span><span class="bank">${esc(short(ev.bank))}</span> <span class="name">${esc(ev.title)}</span></span><span class="when">${esc(when)}</span></div></div>`;
    }
    const past = ev.status !== "scheduled";
    const flags = (ev.flags || []).filter(f => f !== "LPR").map(f => `<span class="tag">${esc(f)}</span>`).join("");
    const exp = ev.expected ? `${esc(ev.expected.label)}${ev.expected.basis ? `<span class="basis">${esc(ev.expected.basis)}</span>` : ""}` :
                (ev.type === "meeting" ? (past ? "Unavailable" : "TBC") : "—");
    let dec = past ? (ev.status === "awaiting" ? "Awaiting confirmation" : "Unavailable") : "Pending";
    if (ev.decision) { const d = dir(ev.decision.move); dec = `<span class="dec ${d}">${glyph[d] || ""} ${esc(ev.decision.label)}</span>${srcPill(ev.decision.src)}`; }
    const out = ev.matched === true ? `<span class="pill">✓ As expected</span>` : ev.matched === false ? `<span class="pill miss">! Surprise</span>` : "";
    const rateRow = ev.bank === "MAS" ? "" : `<dt>Rate in</dt><dd>${esc(ev.rate_before || "Unavailable")}</dd>`;
    return `<div class="card"><div class="row1"><span><span class="bank">${esc(short(ev.bank))}</span> <span class="name">${esc(ev.title)}</span>${flags}</span><span class="when">${esc(when)}</span></div>
      <dl class="kv">${rateRow}<dt>Expected</dt><dd>${exp}</dd><dt>Decision</dt><dd>${dec}${out}</dd>${ev.note ? `<dt>Note</dt><dd>${esc(ev.note)}</dd>` : ""}</dl></div>`;
  }

  function renderDetail(byDay, noData) {
    const el = $("#calDetail"), d = S.sel;
    const list = (byDay[d] || []).slice().sort((a, b) => (a.type === "speech") - (b.type === "speech") || (a.time || "99").localeCompare(b.time || "99"));
    const head = `<h3><span>${fmtDate(d)}</span><span class="mono">${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][new Date(d + "T00:00:00Z").getUTCDay()]}</span></h3>`;
    let body = list.length ? list.map(card).join("") : `<p class="empty">${noData ? "No data for this month." : "No meetings or speeches."}</p>`;
    if (S.calBank !== "ALL") {
      const b = S.banks[S.calBank];
      const nxt = b.next ? `Next: ${b.next.title} ${fmtDate(b.next.date)}${b.next.time ? " " + b.next.time + " SGT" : ""}` : (b.next_note || "");
      body += `<div class="card"><div class="row1"><span><span class="bank">${esc(b.short)}</span> <span class="name">${esc(b.rate_label)}</span></span></div>
        <dl class="kv"><dt>Current</dt><dd>${esc(b.rate ? b.rate.level : "TBC")}${b.rate && b.rate.detail ? `<span class="basis">${esc(b.rate.detail)}</span>` : ""}</dd>
        <dt>Next</dt><dd>${esc(nxt || "TBC")}${b.next && b.next_note ? `<span class="basis">${esc(b.next_note)}</span>` : ""}</dd>${b.access_note ? `<dt>Source</dt><dd><span class="basis" style="margin:0">${esc(b.access_note)}</span></dd>` : ""}</dl></div>`;
    }
    el.innerHTML = head + body;
  }

  /* ---------- feed ---------- */
  async function loadFeedMonth(key) {
    if (S.feed[key]) return;
    try { S.feed[key] = (await getJSON(`data/feed/${key}.json`)).items; } catch (e) { S.feed[key] = []; }
  }
  function feedItems() {
    return S.feedMonths.flatMap(k => S.feed[k] || []).filter(x => S.feedBank === "ALL" || x.bank === S.feedBank)
      .sort((a, b) => b.ts.localeCompare(a.ts));
  }
  function renderFeed() {
    const all = feedItems(), items = all.slice(0, S.feedShown);
    const list = $("#feedList");
    if (!items.length) {
      list.innerHTML = `<li class="empty" style="list-style:none;padding:8px 4px">${S.meta.ai && S.meta.ai.enabled === false ? "Feed not yet populated." : "No remarks in the loaded period."}</li>`;
    } else {
      let lastDay = "", html = "";
      for (const x of items) {
        const day = x.ts.slice(0, 10);
        if (day !== lastDay) { html += `<li class="day-sep">${fmtDate(day)}</li>`; lastDay = day; }
        const g = x.stance === "hawkish" ? "▲" : x.stance === "dovish" ? "▼" : "●";
        const who = x.speaker ? `${esc(x.speaker)}${x.role ? ` <span class="role">· ${esc(x.role)}</span>` : ""}` : (x.kind === "decision" ? "Policy decision" : esc(S.banks[x.bank]?.name || ""));
        html += `<li class="item ${esc(x.stance)}"><div class="meta"><b>${x.date_only ? "—" : x.ts.slice(11, 16)}</b>${esc(short(x.bank))}</div>
          <div><div class="who"><i class="g" aria-label="${esc(x.stance)}">${g}</i> ${who}</div><p>${esc(x.text)}</p></div></li>`;
      }
      list.innerHTML = html;
    }
    const older = S.meta.months.feed.filter(k => !S.feedMonths.includes(k));
    $("#feedMore").hidden = !(all.length > S.feedShown || older.length);
  }
  async function feedMore() {
    const all = feedItems();
    if (all.length > S.feedShown) S.feedShown += 50;
    else {
      const older = S.meta.months.feed.filter(k => !S.feedMonths.includes(k)).sort().reverse()[0];
      if (older) { await loadFeedMonth(older); S.feedMonths.push(older); S.feedShown += 50; }
    }
    renderFeed();
  }

  /* ---------- spectrum ---------- */
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const hex2rgb = h => { h = h.replace("#", ""); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); };
  function mix(a, b, t) { const A = hex2rgb(a), B = hex2rgb(b); return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(",")})`; }
  function colorAt(p, R) { const t = Math.max(-1, Math.min(1, p / R)); return t < 0 ? mix(css("--neu"), css("--dove"), -t) : mix(css("--neu"), css("--hawk"), t); }
  const lean = p => p <= -0.75 ? "dovish" : p <= -0.25 ? "leans dovish" : p < 0.25 ? "centre" : p < 0.75 ? "leans hawkish" : "hawkish";
  let measureCtx;
  function textW(s, bold) { measureCtx = measureCtx || document.createElement("canvas").getContext("2d"); measureCtx.font = `${bold ? 600 : 400} 12px "IBM Plex Sans", system-ui, sans-serif`; return measureCtx.measureText(s).width; }

  function renderSpectrum() {
    const code = S.specBank, d = S.spec[code] || { placed: [], unplaced: [] }, b = S.banks[code] || {};
    $("#specMeta").innerHTML = `<span>${esc(b.name)}${d.committee ? " · " + esc(d.committee) : ""}</span>${d.verified ? `<span>Membership verified ${fmtDate(d.verified)}</span>` : ""}` +
      (code === "FED" ? `<span class="spec-legend"><span><i style="background:var(--ink-3)"></i>2026 voter</span><span><i style="border:2px solid var(--ink-3)"></i>Non-voter</span></span>` : "");
    const chart = $("#specChart"), list = $("#specList");
    const placed = d.placed || [];
    chart.hidden = S.listView; list.hidden = !S.listView;
    if (!placed.length) {
      chart.style.height = "auto";
      chart.innerHTML = `<p class="empty" style="padding:18px 0 8px">${d.committee === null && !(d.unplaced || []).length ? esc(d.note || "No policy committee.") : "No attributable remarks in the last 12 months."}</p>`;
      list.innerHTML = "";
    } else if ((chart.clientWidth || 800) < 600) {
      /* Phones: one row per member (name | track with dot), dovish at top. */
      const maxAbs = Math.max(...placed.map(m => Math.abs(m.position)), 0.5);
      const R = Math.min(2, Math.ceil(maxAbs * 2) / 2 + 0.25);
      const pct = p => 4 + (p + R) / (2 * R) * 92;
      chart.style.height = "auto";
      chart.innerHTML = `<div class="rows"><div class="rows-axis"><span></span><span class="ax"><b>Dovish</b><b>Neutral</b><b>Hawkish</b></span></div>` +
        placed.map(m => {
          const col = colorAt(m.position, R), nonvoter = code === "FED" && m.voter === false;
          return `<div class="row"><span class="nm${m.chair ? " chair" : ""}">${esc(m.name)}<small>${esc(m.role || "")}</small></span>` +
            `<span class="tr"><i class="ln"></i><i class="md"></i><i class="pt${m.chair ? " chair" : ""}${nonvoter ? " nonvoter" : ""}" style="left:${pct(m.position)}%;background:${nonvoter ? "var(--panel)" : col};border-color:${col}"></i></span></div>`;
        }).join("") + `</div>`;
      chart.onmousemove = null;
      list.innerHTML = placed.map(m => `<li>${esc(m.name)} <span class="lean">· ${esc(m.role || "")} · ${lean(m.position)} · latest ${fmtDate(m.last)}</span></li>`).join("");
    } else {
      const W = chart.clientWidth || 800, maxAbs = Math.max(...placed.map(m => Math.abs(m.position)), 0.5);
      const R = Math.min(2, Math.ceil(maxAbs * 2) / 2 + 0.25);
      const x = p => 8 + (p + R) / (2 * R) * (W - 16);
      const laneH = 34, gap = 10, lanes = [], items = placed.map(m => {
        const w = Math.max(textW(m.name, m.chair), textW(m.role || "", false) * 0.88) + 4;
        return { m, cx: x(m.position), w };
      }).sort((a, b) => a.cx - b.cx);
      const order = [];
      for (let k = 0; k < 8; k++) order.push(-(k + 1), k + 1);   // -1 = first lane above, +1 = first lane below
      items.forEach(it => {
        const lx = Math.min(Math.max(it.cx, it.w / 2), W - it.w / 2);
        for (const ln of order) {
          const right = lanes[ln] ?? -Infinity;
          if (lx - it.w / 2 >= right + gap) { lanes[ln] = lx + it.w / 2; it.lane = ln; it.lx = lx; return; }
        }
        it.lane = order[order.length - 1]; it.lx = lx;
      });
      const up = Math.max(1, ...items.filter(i => i.lane < 0).map(i => -i.lane)), down = Math.max(0, ...items.filter(i => i.lane > 0).map(i => i.lane));
      const y0 = 14 + up * laneH, H = y0 + 22 + down * laneH + 28;
      chart.style.height = H + "px";
      let html = `<div class="track" style="top:${y0 - 3}px;left:8px;right:8px"></div><div class="mid" style="left:${x(0)}px;top:${y0 - 10}px;height:20px"></div>` +
        `<span class="end l" style="top:${H - 18}px">Dovish</span><span class="end c" style="left:${x(0)}px;top:${H - 18}px">Neutral</span><span class="end r" style="top:${H - 18}px">Hawkish</span>`;
      items.forEach(it => {
        const ly = it.lane < 0 ? y0 - 12 - (-it.lane) * laneH : y0 + 12 + (it.lane - 1) * laneH;
        const stemTop = it.lane < 0 ? ly + 28 : y0 + 7, stemH = it.lane < 0 ? (y0 - 7) - (ly + 28) : ly - (y0 + 7);
        if (stemH > 2) html += `<div class="stem" style="left:${it.cx}px;top:${stemTop}px;height:${stemH}px"></div>`;
        const col = colorAt(it.m.position, R);
        const nonvoter = code === "FED" && it.m.voter === false;
        html += `<div class="dot${it.m.chair ? " chair" : ""}${nonvoter ? " nonvoter" : ""}" data-i="${esc(it.m.name)}" style="left:${it.cx}px;top:${y0}px;background:${col};${nonvoter ? `border-color:${col}` : ""}"></div>`;
        html += `<div class="lbl${it.m.chair ? " chair" : ""}" style="left:${it.lx}px;top:${ly}px">${esc(it.m.name)}<small>${esc(it.m.role || "")}</small></div>`;
      });
      chart.innerHTML = html;
      chart.onmousemove = e => {
        const dot = e.target.closest(".dot"); const tip = $("#tip");
        if (!dot) { tip.hidden = true; return; }
        const m = placed.find(p => p.name === dot.dataset.i);
        tip.innerHTML = `<b>${esc(m.name)}</b><br>${esc(m.role || "")}${m.secondary ? " (secondary source)" : ""}<br>${m.n} remark${m.n > 1 ? "s" : ""} in 12 months · latest ${fmtDate(m.last)}`;
        tip.hidden = false; tip.style.left = Math.min(e.clientX + 14, innerWidth - 290) + "px"; tip.style.top = (e.clientY + 14) + "px";
      };
      chart.onmouseleave = () => { $("#tip").hidden = true; };
      list.innerHTML = placed.map(m => `<li>${esc(m.name)} <span class="lean">· ${esc(m.role || "")} · ${lean(m.position)} · latest ${fmtDate(m.last)}</span></li>`).join("");
    }
    const un = d.unplaced || [];
    $("#specFoot").innerHTML = (un.length ? `<div><b>No recent attributable remarks:</b> ${un.map(m => esc(m.name)).join(", ")}</div>` : "") +
      (d.note && (placed.length || un.length) ? `<div style="margin-top:4px">${esc(d.note)}</div>` : "");
  }

  /* ---------- boot ---------- */
  async function init() {
    try {
      const [meta, banks, spec] = await Promise.all([getJSON("data/meta.json"), getJSON("data/banks.json"), getJSON("data/spectrum.json")]);
      S.meta = meta; S.order = banks.order; banks.banks.forEach(b => (S.banks[b.code] = b)); S.spec = spec;
    } catch (e) { $("#updated").textContent = "Data unavailable"; return; }
    S.calBank = pref("calBank") || "ALL"; S.feedBank = pref("feedBank") || "ALL"; S.specBank = pref("specBank") || "FED";
    if (S.calBank !== "ALL" && !S.banks[S.calBank]) S.calBank = "ALL";
    if (S.feedBank !== "ALL" && !S.banks[S.feedBank]) S.feedBank = "ALL";
    if (!S.banks[S.specBank]) S.specBank = "FED";
    S.month = S.meta.today.slice(0, 7);
    renderHeader();
    segment($("#calBanks"), true, S.calBank, c => { S.calBank = c; pref("calBank", c); renderCalendar(); });
    segment($("#feedBanks"), true, S.feedBank, c => { S.feedBank = c; pref("feedBank", c); S.feedShown = 50; renderFeed(); });
    segment($("#specBanks"), false, S.specBank, c => { S.specBank = c; pref("specBank", c); renderSpectrum(); });
    $("#prevMonth").onclick = () => { S.month = shiftMonth(S.month, -1); renderCalendar(); };
    $("#nextMonth").onclick = () => { S.month = shiftMonth(S.month, 1); renderCalendar(); };
    $("#todayBtn").onclick = () => { S.month = S.meta.today.slice(0, 7); S.sel = S.meta.today; renderCalendar(); };
    $("#feedMore").onclick = feedMore;
    $("#specView").onclick = e => { S.listView = !S.listView; e.target.setAttribute("aria-pressed", S.listView); renderSpectrum(); };
    $("#themeBtn").onclick = () => {
      const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      document.documentElement.dataset.theme = dark ? "light" : "dark"; pref("theme", document.documentElement.dataset.theme); renderSpectrum();
    };
    renderCalendar();
    const fm = S.meta.months.feed.slice().sort().reverse().slice(0, 2);
    await Promise.all(fm.map(loadFeedMonth)); S.feedMonths = fm; renderFeed();
    renderSpectrum();
    let t; addEventListener("resize", () => { clearTimeout(t); t = setTimeout(renderSpectrum, 120); });
    if (document.fonts) document.fonts.ready.then(renderSpectrum);
  }
  init();
})();
