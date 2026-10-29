/* Central Bank Monitor — renders docs/data/*.json. All times are SGT strings
   produced by the pipeline (no browser time-zone conversion). */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  const S = { meta: null, banks: {}, order: [], members: {}, cal: {}, feed: {}, feedMonths: [], calBank: "ALL", feedBank: "ALL",
              memBank: "FED", memOpen: null, month: null, sel: null, feedShown: 60 };
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
    const m = S.meta, u = m.refreshed || m.updated, ageH = (Date.now() - Date.parse(u)) / 36e5;   // time of the last full source refresh
    $("#updated").textContent = `UPD ${dm(u.slice(0, 10))} ${u.slice(11, 16)} SGT` + (ageH > 30 ? " · OVERDUE" : "");
    const stale = m.stale || [], notes = S.order.map(c => S.banks[c]).filter(b => b.access_note);
    const btn = $("#staleBtn"), pop = $("#stalePanel");
    const L = m.language || {}, langLate = (L.pending || 0) > 0 && (!L.last_run || (Date.now() - Date.parse(L.last_run)) / 36e5 > 30);
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
        nextCell += `<span class="in-inline"> · ${inCell}</span>`;
      }
      let ex = `<span class="exp-tbc">TBC</span>`;
      if (nx && nx.expected) {
        const k = dirOf(nx.expected_move ?? nx.expected_dir), dirOnly = nx.expected_move == null && c !== "MAS";
        ex = `<span class="${k}" title="${esc(nx.basis || "")}">${G[k] || ""} ${esc(nx.expected.replace(/\s*\(size not polled\)/i, "").toUpperCase())}</span>${dirOnly ? `<span class="sub"> size not polled</span>` : ""}`;
      }
      const rl = rate ? (rate.detail ? `${esc(rate.level)} <span class="sub clip" title="${esc(rate.detail)}">${esc(rate.detail)}</span>` : esc(rate.level)) : `<span class="exp-tbc">TBC</span>`;
      return `<tr class="brow" data-c="${c}"><td class="c-bank"><span class="code">${esc(b.short.toUpperCase())}</span><span class="nm">${esc(b.name)}</span></td>
        <td class="c-rate"><span class="rate">${rl}</span>${rate && rate.detail ? "" : ` <span class="sub opt">${esc(b.rate_label)}</span>`}</td><td class="c-last"><span class="lbl">LAST</span>${lastCell}</td>
        <td class="c-next"><span class="lbl">NEXT</span>${nextCell}</td><td class="in c-in">${inCell}</td><td class="c-exp"><span class="lbl">EXP</span>${ex}</td></tr>`;
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

  /* One calendar line: chip = decision/expectation, txt = what it is. */
  function line(e) {
    if (e.type === "speech") {
      const m = e.title.match(/([A-Z][\w'’-]+)\s+(Speaks|Testifies)\b/);
      return { cls: "sp", txt: m ? `${m[1]} ${m[2].toLowerCase()}` : e.title.replace(new RegExp(`^${short(e.bank)}\\s+`, "i"), ""), minor: true };
    }
    if (e.type === "release") return { cls: "rl", txt: e.title, minor: true };
    if (e.decision) {
      const k = dirOf(e.decision.move);
      if (e.type === "lpr") return { cls: k, chip: "LPR " + (k === "hd" ? "unch" : `${e.decision.move > 0 ? "+" : "−"}${Math.abs(e.decision.move)}`) };
      const chip = e.bank === "MAS" ? (e.decision.move === 0 ? "Unch" : e.decision.move > 0 ? "Tighten" : "Ease") : k === "hd" ? "Hold" : `${e.decision.move > 0 ? "+" : "−"}${Math.abs(e.decision.move)}`;
      return { cls: k, chip };
    }
    if (e.expected) { const mv = e.expected.move, dr = mv ?? e.expected.dir;
      return { cls: "ex", chip: "Exp " + (dr === 0 ? "hold" : mv != null ? `${mv > 0 ? "+" : "−"}${Math.abs(mv)}` : dr > 0 ? "hike" : "cut") }; }
    return { cls: "ex", chip: e.status === "awaiting" ? "Pending" : "Exp TBC" };
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
      const shown = list.slice(0, 5).map(e => { const r = line(e);
        return r.minor ? `<div class="ev minor"><span class="c">${esc(short(e.bank))}</span><span class="r">${esc(r.txt)}</span></div>`
          : `<div class="ev"><span class="chip ${r.cls}">${esc(r.chip)}</span><span class="c">${esc(short(e.bank))}</span>${e.time ? `<span class="t">${e.time}</span>` : ""}</div>`; }).join("");
      const dots = list.slice(0, 6).map(e => `<i class="${line(e).cls}"></i>`).join("");
      cells.push(`<button class="day${wd > 4 ? " wk" : ""}${iso === S.meta.today ? " today" : ""}${iso === S.sel ? " sel" : ""}" data-d="${iso}" aria-label="${d} ${MON[m - 1]}: ${list.length} items">` +
                 `<span class="dn">${d}</span>${shown}${list.length > 5 ? `<span class="more-ev">+${list.length - 5} more</span>` : ""}<span class="dots">${dots}</span></button>`);
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
    const dirOnly = e.bank !== "MAS" && e.expected && e.expected.move == null;
    const out = e.matched === true ? `<span class="pill">✓ ${dirOnly ? "DIRECTION AS EXPECTED" : "AS EXPECTED"}</span>`
      : e.matched === false ? `<span class="pill miss">! ${dirOnly ? "DIRECTION SURPRISE" : "SURPRISE"}</span>` : "";
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
          <div><div class="who"><i aria-label="${esc(x.stance)}">${g}</i> <span class="bk bk-inline">${esc(short(x.bank).toUpperCase())}</span>${who}</div><p>${esc(x.text)}</p></div>
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

  /* ---------- committees ---------- */
  const shortTs = x => x.date_only ? dmy(x.ts.slice(0, 10)) : `${dmy(x.ts.slice(0, 10))} ${x.ts.slice(11, 16)}`;
  function renderMembers() {
    const code = S.memBank, d = S.members[code] || { members: [] }, b = S.banks[code] || {}, ms = d.members || [];
    $("#memMeta").innerHTML = `<span>${esc(b.name)}${d.committee ? " · " + esc(d.committee) : ""}</span>` +
      (d.verified ? `<span>Membership verified ${dmy(d.verified)}${d.src ? " · " + ext(d.src, "official list") : ""}</span>` : "") +
      (code === "FED" ? `<span><span class="vt">Voter</span> 2026 FOMC voter</span>` : "") +
      (d.note ? `<span class="note">${esc(d.note)}</span>` : "");
    if (!ms.length) { $("#memList").innerHTML = `<li class="empty">${esc(d.note || "No policy committee.")}</li>`; return; }
    $("#memList").innerHTML = ms.map((m, i) => {
      const open = S.memOpen === m.name, n = m.comments.length;
      const said = m.comments.map(x => `<li class="${esc(x.stance)}"><span class="when">${shortTs(x)}</span><p>${esc(x.text)}</p>` +
        `<span class="sr">${x.url ? ext(x.url, x.src || "Source") : esc(x.src || "")}</span></li>`).join("");
      return `<li class="mem${open ? " open" : ""}"><button class="mrow" data-i="${i}" aria-expanded="${open}">` +
        `<span class="mn${m.chair ? " chair" : ""}">${esc(m.name)}</span><span class="mr">${esc(m.role || "")}</span>` +
        `<span class="mx">${code === "FED" && m.voter ? `<span class="vt">Voter</span>` : ""}${n ? `<span class="cnt">${n} recent</span>` : ""}<span class="chev" aria-hidden="true">${open ? "−" : "+"}</span></span></button>` +
        (open ? `<div class="mbody"><h4>Background</h4><p class="bio">${m.bio ? esc(m.bio) + (m.bio_src ? ` <span class="sr">${ext(m.bio_src, "Source")}</span>` : "") : ""}</p>` +
                `<h4>Latest remarks</h4><ol class="said">${said}</ol></div>` : "") + `</li>`;
    }).join("");
  }

  /* ---------- boot ---------- */
  async function init() {
    try {
      const [meta, banks, members] = await Promise.all([getJSON("data/meta.json"), getJSON("data/banks.json"), getJSON("data/members.json")]);
      S.meta = meta; S.order = banks.order; banks.banks.forEach(b => (S.banks[b.code] = b)); S.members = members;
    } catch (e) { $("#updated").textContent = "DATA UNAVAILABLE"; return; }
    const ok = c => c === "ALL" || S.banks[c];
    S.calBank = ok(pref("calBank")) && pref("calBank") ? pref("calBank") : "ALL";
    S.feedBank = ok(pref("feedBank")) && pref("feedBank") ? pref("feedBank") : "ALL";
    S.memBank = S.banks[pref("memBank")] ? pref("memBank") : "FED";
    S.month = S.meta.today.slice(0, 7);
    renderHeader(); renderBoard();
    keys($("#calBanks"), true, S.calBank, c => { S.calBank = c; pref("calBank", c); renderCalendar(); });
    keys($("#feedBanks"), true, S.feedBank, c => { S.feedBank = c; pref("feedBank", c); S.feedShown = 60; renderFeed(); });
    keys($("#memBanks"), false, S.memBank, c => { S.memBank = c; S.memOpen = null; pref("memBank", c); renderMembers(); });
    $("#memList").onclick = e => { const b = e.target.closest("button.mrow"); if (!b) return;
      const m = S.members[S.memBank].members[+b.dataset.i]; S.memOpen = S.memOpen === m.name ? null : m.name; renderMembers(); };
    $("#prevMonth").onclick = () => { S.month = shiftMonth(S.month, -1); renderCalendar(); };
    $("#nextMonth").onclick = () => { S.month = shiftMonth(S.month, 1); renderCalendar(); };
    $("#todayBtn").onclick = () => { S.month = S.meta.today.slice(0, 7); S.sel = S.meta.today; renderCalendar(); };
    $("#feedMore").onclick = feedMore;
    renderCalendar();
    const fm = S.meta.months.feed.slice().sort().reverse().slice(0, 2);
    await Promise.all(fm.map(loadFeedMonth)); S.feedMonths = fm; renderFeed();
    renderMembers();
  }
  init();
})();
