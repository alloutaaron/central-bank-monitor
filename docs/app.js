/* Central Bank Monitor — renders docs/data/*.json. All times are SGT strings
   produced by the pipeline (no browser time-zone conversion). */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  const S = { meta: null, banks: {}, order: [], spec: {}, cal: {}, feed: {}, feedMonths: [], calBank: "ALL", feedBank: "ALL",
              specBank: "FED", month: null, sel: null, feedShown: 60, listView: false };
  const pref = (k, v) => { try { if (v === undefined) return localStorage.getItem("cbm-" + k); localStorage.setItem("cbm-" + k, v); } catch (e) { return null; } };
  const getJSON = async url => { const r = await fetch(url, { cache: "no-cache" }); if (!r.ok) throw new Error(url); return r.json(); };
  const dmy = iso => { const [y, m, d] = iso.split("-").map(Number); return `${String(d).padStart(2, "0")} ${MON[m - 1]} ${y}`; };
  const dm = iso => { const [, m, d] = iso.split("-").map(Number); return `${String(d).padStart(2, "0")} ${MON[m - 1]}`; };
  const short = c => (S.banks[c] || {}).short || c;
  const dirOf = mv => mv == null ? null : mv > 0 ? "up" : mv < 0 ? "dn" : "hd";
  const G = { up: "▲", dn: "▼", hd: "■" };
  const ext = (url, label) => url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)} ↗</a>` : esc(label);
  const daysBetween = (a, b) => Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 864e5);

  function keys(el, withAll, current, onPick) {
    const codes = (withAll ? ["ALL"] : []).concat(S.order);
    el.innerHTML = codes.map(c => `<button role="tab" data-c="${c}" aria-selected="${c === current}">${c === "ALL" ? "ALL" : esc(short(c))}</button>`).join("");
    el.onclick = e => { const b = e.target.closest("button"); if (!b) return; el.querySelectorAll("button").forEach(x => x.setAttribute("aria-selected", x === b)); onPick(b.dataset.c); };
  }
  function selectKey(el, code) { el.querySelectorAll("button").forEach(x => x.setAttribute("aria-selected", x.dataset.c === code)); }

  /* ---------- command bar ---------- */
  function renderHeader() {
    const m = S.meta, u = m.updated, ageH = (Date.now() - Date.parse(u)) / 36e5;
    $("#updated").textContent = `UPD ${dm(u.slice(0, 10))} ${u.slice(11, 16)} SGT` + (ageH > 30 ? " · OVERDUE" : "");
    const stale = m.stale || [], notes = S.order.map(c => S.banks[c]).filter(b => b.access_note);
    const btn = $("#staleBtn"), pop = $("#stalePanel");
    const L = m.language || {}, langLate = !L.last_run || (Date.now() - Date.parse(L.last_run)) / 36e5 > 30;
    btn.hidden = false; btn.classList.toggle("bad", stale.length > 0 || langLate);
    btn.textContent = stale.length ? `${stale.length} STALE` : langLate ? "LANGUAGE STEP LATE" : "SOURCES";
    const label = sid => { const [b, ...rest] = sid.split(":"); return (S.banks[b] ? short(b) : b) + " · " + rest.join(":").replace(/-/g, " "); };
    pop.innerHTML = (stale.length ? `<h3>Failed on the latest run</h3><ul>${stale.map(s => `<li><b>${esc(label(s.source))}</b> · last OK ${s.last_ok ? esc(s.last_ok.slice(0, 16).replace("T", " ")) : "never"}</li>`).join("")}</ul>`
                                  : `<h3>Latest run</h3><ul><li>All sources refreshed.</li></ul>`) +
      (() => { const L = m.language || {}; const age = L.last_run ? (Date.now() - Date.parse(L.last_run)) / 36e5 : null;
        return `<h3>Language step (paraphrase, translation, stance, expectations)</h3><ul><li>${L.last_run ? "Last run " + esc(L.last_run.slice(0, 16).replace("T", " ")) + " SGT" + (age > 30 ? " · OVERDUE" : "") : "Not run yet"} · ${L.pending || 0} items waiting</li></ul>`; })() +
      `<h3>Known access limits</h3><ul>${notes.map(b => `<li><b>${esc(b.short)}</b> · ${esc(b.access_note)}</li>`).join("")}</ul>`;
    btn.onclick = e => { e.stopPropagation(); pop.hidden = !pop.hidden; btn.setAttribute("aria-expanded", !pop.hidden); };
    document.addEventListener("click", e => { if (!pop.hidden && !pop.contains(e.target)) { pop.hidden = true; btn.setAttribute("aria-expanded", "false"); } });
  }

  /* ---------- rates board ---------- */
  function renderBoard() {
    const today = S.meta.today;
    const rows = S.order.map(c => {
      const b = S.banks[c], rate = b.rate, last = b.last, nx = b.next;
      const lastCell = last ? `<span class="mv ${dirOf(last.move)}">${G[dirOf(last.move)] || ""} ${last.move === 0 ? "HOLD" : (last.move > 0 ? "+" : "") + last.move}</span><span class="sub">${dm(last.date)}</span>` : `<span class="exp-tbc">—</span>`;
      let nextCell = `<span class="exp-tbc">${esc((b.next_note || "TBC").toUpperCase())}</span>`, inCell = "";
      if (nx) {
        nextCell = `${dm(nx.date)}${nx.time ? " " + nx.time : ""}`;
        const d = daysBetween(today, nx.date);
        inCell = d <= 0 ? "TODAY" : `${d}D`;
      }
      let ex = `<span class="exp-tbc">TBC</span>`;
      if (nx && nx.expected) {
        const k = dirOf(nx.expected_move);
        ex = `<span class="${k}" title="${esc(nx.basis || "")}">${G[k] || ""} ${esc(nx.expected.toUpperCase())}</span>`;
      }
      const rl = rate ? (rate.detail ? `${esc(rate.level)} <span class="sub clip" title="${esc(rate.detail)}">${esc(rate.detail)}</span>` : esc(rate.level)) : `<span class="exp-tbc">TBC</span>`;
      return `<tr class="brow" data-c="${c}"><td><span class="code">${esc(b.short.toUpperCase())}</span><span class="nm">${esc(b.name)}</span></td>
        <td><span class="rate">${rl}</span> <span class="sub opt">${esc(b.rate_label)}</span></td><td>${lastCell}</td>
        <td>${nextCell}</td><td class="in">${inCell}</td><td>${ex}</td></tr>`;
    }).join("");
    $("#boardTbl").innerHTML = `<thead><tr><th>Bank</th><th>Policy rate</th><th>Last move</th><th>Next decision</th><th>In</th><th>Expected</th></tr></thead><tbody>${rows}</tbody>`;
    $("#boardTbl").onclick = e => {
      const tr = e.target.closest("tr.brow"); if (!tr) return;
      const c = tr.dataset.c, nx = S.banks[c].next;
      S.calBank = c; pref("calBank", c); selectKey($("#calBanks"), c);
      if (nx) { S.month = nx.date.slice(0, 7); S.sel = nx.date; }
      renderCalendar(); $("#calendar").scrollIntoView({ behavior: "smooth", block: "start" });
    };
  }

  /* ---------- calendar ---------- */
  async function loadMonth(key) {
    if (S.cal[key] !== undefined) return S.cal[key];
    if (!S.meta.months.calendar.includes(key)) return (S.cal[key] = null);
    try { S.cal[key] = (await getJSON(`data/calendar/${key}.json`)).events; } catch (e) { S.cal[key] = null; }
    return S.cal[key];
  }
  const shiftMonth = (key, n) => { let [y, m] = key.split("-").map(Number); m += n; while (m > 12) { m -= 12; y++; } while (m < 1) { m += 12; y--; } return `${y}-${String(m).padStart(2, "0")}`; };
  const rank = e => ({ meeting: 0, lpr: 0, "rate-change": 0, release: 1, speech: 2 }[e.type] ?? 3);

  function line(e) {
    if (e.type === "speech") return { g: "◦", cls: "sp", txt: e.title.replace(/^(\w+ )?(\w+\.? )?/, ""), minor: true };
    if (e.type === "release") return { g: "◇", cls: "rl", txt: e.title.toUpperCase(), minor: true };
    if (e.decision) {
      const k = dirOf(e.decision.move);
      const txt = e.bank === "MAS" ? (e.decision.move === 0 ? "UNCH" : e.decision.move > 0 ? "TIGHTEN" : "EASE") : k === "hd" ? "HOLD" : `${e.decision.move > 0 ? "+" : ""}${e.decision.move}`;
      return { g: G[k], cls: k, txt };
    }
    if (e.expected) return { g: "E", cls: "ex", txt: e.expected.move === 0 ? "HOLD" : `${e.expected.move > 0 ? "+" : ""}${e.expected.move}` };
    return { g: "E", cls: "ex", txt: e.status === "awaiting" ? "PENDING" : "TBC" };
  }

  async function renderCalendar() {
    const key = S.month, [y, m] = key.split("-").map(Number);
    $("#monthLabel").textContent = `${MON[m - 1]} ${y}`;
    const events = (await loadMonth(key)) || [];
    const vis = events.filter(e => S.calBank === "ALL" || e.bank === S.calBank);
    const byDay = {};
    vis.forEach(e => (byDay[e.date] = byDay[e.date] || []).push(e));
    Object.values(byDay).forEach(l => l.sort((a, b) => rank(a) - rank(b) || (a.time || "99").localeCompare(b.time || "99")));
    const first = new Date(Date.UTC(y, m - 1, 1)), lead = (first.getUTCDay() + 6) % 7, days = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const cells = [];
    for (let i = 0; i < lead; i++) cells.push(`<div class="day out" aria-hidden="true"></div>`);
    for (let d = 1; d <= days; d++) {
      const iso = `${key}-${String(d).padStart(2, "0")}`, list = byDay[iso] || [], wd = (lead + d - 1) % 7;
      const shown = list.slice(0, 5).map(e => { const r = line(e); return `<div class="ev${r.minor ? " minor" : ""}"><i class="g ${r.cls}">${r.g}</i><span class="c">${esc(short(e.bank).toUpperCase())}</span>${e.time && !r.minor ? `<span class="t">${e.time}</span>` : ""}<span class="r">${esc(r.txt)}</span></div>`; }).join("");
      const dots = list.slice(0, 6).map(e => `<i class="${line(e).cls}"></i>`).join("");
      cells.push(`<button class="day${wd > 4 ? " wk" : ""}${iso === S.meta.today ? " today" : ""}${iso === S.sel ? " sel" : ""}" data-d="${iso}" aria-label="${d} ${MON[m - 1]}: ${list.length} items">` +
                 `<span class="dn">${d}</span>${shown}${list.length > 5 ? `<span class="more-ev">+${list.length - 5} MORE</span>` : ""}<span class="dots">${dots}</span></button>`);
    }
    while (cells.length % 7) cells.push(`<div class="day out" aria-hidden="true"></div>`);
    const grid = $("#calGrid"); grid.innerHTML = cells.join("");
    grid.onclick = e => { const b = e.target.closest("button.day"); if (!b) return; S.sel = b.dataset.d; grid.querySelectorAll(".day.sel").forEach(x => x.classList.remove("sel")); b.classList.add("sel"); renderDetail(byDay); };
    if (!S.sel || S.sel.slice(0, 7) !== key) {
      S.sel = S.meta.today.slice(0, 7) === key ? S.meta.today : (Object.keys(byDay).sort()[0] || `${key}-01`);
      const b = grid.querySelector(`[data-d="${S.sel}"]`); if (b) b.classList.add("sel");
    }
    renderDetail(byDay, !S.meta.months.calendar.includes(key));
  }

  const srcPill = k => k ? `<span class="pill">${k === "official" ? "OFFICIAL" : k === "BIS" ? "BIS DATA" : k === "wire" ? "WIRE REPORT" : esc(k)}</span>` : "";
  function linksRow(links) {
    if (!links || !links.length) return "";
    return `<div class="lnk">${links.map(l => l.status === "published" && l.url ? ext(l.url, l.title + (l.date ? " " + dm(l.date) : ""))
      : `<span class="sch" title="${esc(l.basis || "")}">${esc(l.title)}${l.date ? " · " + dm(l.date) : ""}${l.basis ? " (scheduled)" : ""}</span>`).join("")}</div>`;
  }

  function card(e) {
    const when = e.time ? `${e.time} SGT` + (e.local_date && e.local_date !== e.date ? ` · ${dm(e.local_date)} LOCAL` : "") : (e.type === "meeting" ? "TIME TBC" : "");
    if (e.type === "speech") return `<div class="card"><div class="r1"><span><span class="bk">${esc(short(e.bank).toUpperCase())}</span> <span class="nm">${esc(e.title)}</span></span><span class="when">${esc(when)}</span></div></div>`;
    if (e.type === "release") {
      return `<div class="card"><div class="r1"><span><span class="bk">${esc(short(e.bank).toUpperCase())}</span> <span class="nm">${e.url && e.status === "done" ? ext(e.url, e.title) : esc(e.title)}</span></span><span class="when">${e.status === "done" ? "PUBLISHED" : "SCHEDULED"}</span></div>
        <dl class="kv">${e.meeting ? `<dt>Meeting</dt><dd>${dmy(e.meeting)}</dd>` : ""}${e.basis && e.status !== "done" ? `<dt>Date from</dt><dd><span class="basis" style="margin:0">${esc(e.basis)}</span></dd>` : ""}</dl></div>`;
    }
    const past = e.status !== "scheduled";
    const flags = (e.flags || []).filter(f => f !== "LPR").map(f => `<span class="tag">${esc(f)}</span>`).join("");
    const exp = e.expected ? `${esc(e.expected.label)}${e.expected.basis ? `<span class="basis">${esc(e.expected.basis)}</span>` : ""}` : (e.type === "meeting" ? (past ? "Unavailable" : "TBC") : "—");
    let dec = past ? (e.status === "awaiting" ? "Awaiting confirmation" : "Unavailable") : "Pending";
    if (e.decision) { const k = dirOf(e.decision.move); dec = `<span class="${k}">${G[k] || ""}</span> ${esc(e.decision.label)}${srcPill(e.decision.src)}`; }
    const out = e.matched === true ? `<span class="pill">✓ AS EXPECTED</span>` : e.matched === false ? `<span class="pill miss">! SURPRISE</span>` : "";
    const rateRow = e.bank === "MAS" ? "" : `<dt>Rate in</dt><dd>${esc(e.rate_before || "Unavailable")}</dd>`;
    return `<div class="card"><div class="r1"><span><span class="bk">${esc(short(e.bank).toUpperCase())}</span> <span class="nm">${esc(e.title)}</span>${flags}</span><span class="when">${esc(when)}</span></div>
      <dl class="kv">${rateRow}<dt>Expected</dt><dd>${exp}</dd><dt>Decision</dt><dd>${dec}${out}</dd>${e.note ? `<dt>Note</dt><dd>${esc(e.note)}</dd>` : ""}</dl>${linksRow(e.links)}</div>`;
  }

  function renderDetail(byDay, noData) {
    const d = S.sel, list = byDay[d] || [];
    let html = `<h3><span>${dmy(d)}</span><span>${["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"][new Date(d + "T00:00:00Z").getUTCDay()]}</span></h3>`;
    html += list.length ? list.map(card).join("") : `<p class="empty">${noData ? "No data for this month." : "No meetings, releases or speeches."}</p>`;
    if (S.calBank !== "ALL") {
      const b = S.banks[S.calBank];
      const nx = b.next ? `${b.next.title} ${dmy(b.next.date)}${b.next.time ? " " + b.next.time + " SGT" : ""}` : (b.next_note || "TBC");
      html += `<div class="card"><div class="r1"><span><span class="bk">${esc(b.short.toUpperCase())}</span> <span class="nm">${esc(b.rate_label)}</span></span></div>
        <dl class="kv"><dt>Current</dt><dd>${esc(b.rate ? b.rate.level : "TBC")}${b.rate && b.rate.detail ? `<span class="basis">${esc(b.rate.detail)}</span>` : ""}</dd>
        <dt>Next</dt><dd>${esc(nx)}${b.next && b.next_note ? `<span class="basis">${esc(b.next_note)}</span>` : ""}</dd>${b.access_note ? `<dt>Source</dt><dd><span class="basis" style="margin:0">${esc(b.access_note)}</span></dd>` : ""}</dl></div>`;
    }
    $("#calDetail").innerHTML = html;
  }

  /* ---------- feed ---------- */
  async function loadFeedMonth(k) { if (S.feed[k]) return; try { S.feed[k] = (await getJSON(`data/feed/${k}.json`)).items; } catch (e) { S.feed[k] = []; } }
  const feedItems = () => S.feedMonths.flatMap(k => S.feed[k] || []).filter(x => S.feedBank === "ALL" || x.bank === S.feedBank).sort((a, b) => b.ts.localeCompare(a.ts));
  function renderFeed() {
    const all = feedItems(), items = all.slice(0, S.feedShown), list = $("#feedList");
    if (!items.length) list.innerHTML = `<li class="empty" style="list-style:none;padding:6px 4px">No remarks in the loaded period.</li>`;
    else {
      let last = "", h = "";
      for (const x of items) {
        const day = x.ts.slice(0, 10);
        if (day !== last) { h += `<li class="dsep">${dmy(day)}</li>`; last = day; }
        const g = x.stance === "hawkish" ? "▲" : x.stance === "dovish" ? "▼" : "●";
        const who = x.speaker ? `${esc(x.speaker)}${x.role ? ` <span class="role">· ${esc(x.role)}</span>` : ""}` : (x.kind === "decision" ? "Policy decision" : esc(S.banks[x.bank]?.name || ""));
        h += `<li class="it ${esc(x.stance)}"><span class="tm">${x.date_only ? "—" : x.ts.slice(11, 16)}</span><span class="bk bkcol">${esc(short(x.bank).toUpperCase())}</span>
          <div><div class="who"><i aria-label="${esc(x.stance)}">${g}</i> ${who}</div><p>${esc(x.text)}</p></div>
          <span class="sr">${x.url ? ext(x.url, (x.src || "Source").toUpperCase()) : esc((x.src || "").toUpperCase())}</span></li>`;
      }
      list.innerHTML = h;
    }
    const older = S.meta.months.feed.filter(k => !S.feedMonths.includes(k));
    $("#feedMore").hidden = !(all.length > S.feedShown || older.length);
  }
  async function feedMore() {
    if (feedItems().length > S.feedShown) S.feedShown += 60;
    else { const o = S.meta.months.feed.filter(k => !S.feedMonths.includes(k)).sort().reverse()[0]; if (o) { await loadFeedMonth(o); S.feedMonths.push(o); S.feedShown += 60; } }
    renderFeed();
  }

  /* ---------- spectrum ---------- */
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const rgb = h => { h = h.replace("#", ""); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); };
  const mix = (a, b, t) => { const A = rgb(a), B = rgb(b); return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(",")})`; };
  const colorAt = (p, R) => { const t = Math.max(-1, Math.min(1, p / R)); return t < 0 ? mix(css("--neu"), css("--dove"), -t) : mix(css("--neu"), css("--hawk"), t); };
  const lean = p => p <= -0.75 ? "dovish" : p <= -0.25 ? "leans dovish" : p < 0.25 ? "centre" : p < 0.75 ? "leans hawkish" : "hawkish";
  let mctx; const textW = (s, b) => { mctx = mctx || document.createElement("canvas").getContext("2d"); mctx.font = `${b ? 500 : 400} 12px "IBM Plex Sans", sans-serif`; return mctx.measureText(s).width; };

  function renderSpectrum() {
    const code = S.specBank, d = S.spec[code] || { placed: [], unplaced: [] }, b = S.banks[code] || {}, placed = d.placed || [];
    $("#specMeta").innerHTML = `<span>${esc(b.name)}${d.committee ? " · " + esc(d.committee) : ""}</span>${d.verified ? `<span>MEMBERSHIP VERIFIED ${dmy(d.verified)}</span>` : ""}` +
      (code === "FED" ? `<span class="leg"><span><i style="background:var(--ink-3)"></i>2026 VOTER</span> <span><i style="border:2px solid var(--ink-3)"></i>NON-VOTER</span></span>` : "");
    const chart = $("#specChart"), list = $("#specList");
    chart.hidden = S.listView; list.hidden = !S.listView;
    list.innerHTML = placed.map(m => `<li>${esc(m.name)} <span class="lean">· ${esc(m.role || "")} · ${lean(m.position)} · latest ${dmy(m.last)}</span></li>`).join("");
    if (!placed.length) { chart.style.height = "auto"; chart.innerHTML = `<p class="empty" style="padding:14px 0 6px">${d.committee === null && !(d.unplaced || []).length ? esc(d.note || "No policy committee.") : "No attributable remarks in the last 12 months."}</p>`; }
    else {
      const maxAbs = Math.max(...placed.map(m => Math.abs(m.position)), 0.5), R = Math.min(2, Math.ceil(maxAbs * 2) / 2 + 0.25);
      if ((chart.clientWidth || 800) < 600) {
        const pct = p => 4 + (p + R) / (2 * R) * 92;
        chart.style.height = "auto";
        chart.innerHTML = `<div class="rows"><div class="rows-axis"><span></span><span class="ax"><b>DOVISH</b><b>NEUTRAL</b><b>HAWKISH</b></span></div>` + placed.map(m => {
          const col = colorAt(m.position, R), nv = code === "FED" && m.voter === false;
          return `<div class="row"><span class="nm${m.chair ? " chair" : ""}">${esc(m.name)}<small>${esc(m.role || "")}</small></span><span class="tr"><i class="ln"></i><i class="md"></i><i class="pt${m.chair ? " chair" : ""}${nv ? " nonvoter" : ""}" style="left:${pct(m.position)}%;background:${nv ? "#000" : col};border-color:${col}"></i></span></div>`;
        }).join("") + `</div>`;
        chart.onmousemove = null;
      } else {
        const W = chart.clientWidth, x = p => 8 + (p + R) / (2 * R) * (W - 16), laneH = 34, gap = 10, lanes = [];
        const items = placed.map(m => ({ m, cx: x(m.position), w: Math.max(textW(m.name, m.chair), (m.role || "").length * 6.3) + 4 })).sort((a, b) => a.cx - b.cx);
        const order = []; for (let k = 0; k < 8; k++) order.push(-(k + 1), k + 1);
        items.forEach(it => {
          const lx = Math.min(Math.max(it.cx, it.w / 2), W - it.w / 2);
          for (const ln of order) { const right = lanes[ln] ?? -Infinity; if (lx - it.w / 2 >= right + gap) { lanes[ln] = lx + it.w / 2; it.lane = ln; it.lx = lx; return; } }
          it.lane = order[order.length - 1]; it.lx = lx;
        });
        const up = Math.max(1, ...items.filter(i => i.lane < 0).map(i => -i.lane)), down = Math.max(0, ...items.filter(i => i.lane > 0).map(i => i.lane));
        const y0 = 14 + up * laneH, H = y0 + 22 + down * laneH + 26;
        chart.style.height = H + "px";
        let h = `<div class="track" style="top:${y0 - 2}px;left:8px;right:8px"></div><div class="mid" style="left:${x(0)}px;top:${y0 - 10}px;height:20px"></div>` +
          `<span class="end" style="left:0;top:${H - 16}px">DOVISH</span><span class="end c" style="left:${x(0)}px;top:${H - 16}px">NEUTRAL</span><span class="end r" style="top:${H - 16}px">HAWKISH</span>`;
        items.forEach(it => {
          const ly = it.lane < 0 ? y0 - 12 - (-it.lane) * laneH : y0 + 12 + (it.lane - 1) * laneH;
          const st = it.lane < 0 ? ly + 28 : y0 + 7, sh = it.lane < 0 ? (y0 - 7) - (ly + 28) : ly - (y0 + 7);
          if (sh > 2) h += `<div class="stem" style="left:${it.cx}px;top:${st}px;height:${sh}px"></div>`;
          const col = colorAt(it.m.position, R), nv = code === "FED" && it.m.voter === false;
          h += `<div class="dot${it.m.chair ? " chair" : ""}${nv ? " nonvoter" : ""}" data-i="${esc(it.m.name)}" style="left:${it.cx}px;top:${y0}px;background:${col};${nv ? `border-color:${col}` : ""}"></div>`;
          h += `<div class="lbl${it.m.chair ? " chair" : ""}" style="left:${it.lx}px;top:${ly}px">${esc(it.m.name)}<small>${esc(it.m.role || "")}</small></div>`;
        });
        chart.innerHTML = h;
        chart.onmousemove = e => {
          const dot = e.target.closest(".dot"), tip = $("#tip"); if (!dot) { tip.hidden = true; return; }
          const m = placed.find(p => p.name === dot.dataset.i);
          tip.innerHTML = `<b>${esc(m.name)}</b> · ${esc(m.role || "")}<br>${m.n} remark${m.n > 1 ? "s" : ""} in 12 months · latest ${dmy(m.last)}`;
          tip.hidden = false; tip.style.left = Math.min(e.clientX + 14, innerWidth - 310) + "px"; tip.style.top = (e.clientY + 14) + "px";
        };
        chart.onmouseleave = () => { $("#tip").hidden = true; };
      }
    }
    const un = d.unplaced || [];
    $("#specFoot").innerHTML = (un.length ? `<div><b>No recent attributable remarks:</b> ${un.map(m => esc(m.name)).join(", ")}</div>` : "") + (d.note && (placed.length || un.length) ? `<div style="margin-top:3px">${esc(d.note)}</div>` : "");
  }

  /* ---------- boot ---------- */
  async function init() {
    try {
      const [meta, banks, spec] = await Promise.all([getJSON("data/meta.json"), getJSON("data/banks.json"), getJSON("data/spectrum.json")]);
      S.meta = meta; S.order = banks.order; banks.banks.forEach(b => (S.banks[b.code] = b)); S.spec = spec;
    } catch (e) { $("#updated").textContent = "DATA UNAVAILABLE"; return; }
    const ok = c => c === "ALL" || S.banks[c];
    S.calBank = ok(pref("calBank")) && pref("calBank") ? pref("calBank") : "ALL";
    S.feedBank = ok(pref("feedBank")) && pref("feedBank") ? pref("feedBank") : "ALL";
    S.specBank = S.banks[pref("specBank")] ? pref("specBank") : "FED";
    S.month = S.meta.today.slice(0, 7);
    renderHeader(); renderBoard();
    keys($("#calBanks"), true, S.calBank, c => { S.calBank = c; pref("calBank", c); renderCalendar(); });
    keys($("#feedBanks"), true, S.feedBank, c => { S.feedBank = c; pref("feedBank", c); S.feedShown = 60; renderFeed(); });
    keys($("#specBanks"), false, S.specBank, c => { S.specBank = c; pref("specBank", c); renderSpectrum(); });
    $("#prevMonth").onclick = () => { S.month = shiftMonth(S.month, -1); renderCalendar(); };
    $("#nextMonth").onclick = () => { S.month = shiftMonth(S.month, 1); renderCalendar(); };
    $("#todayBtn").onclick = () => { S.month = S.meta.today.slice(0, 7); S.sel = S.meta.today; renderCalendar(); };
    $("#feedMore").onclick = feedMore;
    $("#specView").onclick = e => { S.listView = !S.listView; e.target.setAttribute("aria-pressed", S.listView); renderSpectrum(); };
    renderCalendar();
    const fm = S.meta.months.feed.slice().sort().reverse().slice(0, 2);
    await Promise.all(fm.map(loadFeedMonth)); S.feedMonths = fm; renderFeed();
    renderSpectrum();
    let t; addEventListener("resize", () => { clearTimeout(t); t = setTimeout(renderSpectrum, 120); });
    if (document.fonts) document.fonts.ready.then(renderSpectrum);
  }
  init();
})();
