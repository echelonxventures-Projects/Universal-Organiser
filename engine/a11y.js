/* Accessibility for every page (the server adds this file to each page it sends):
   - "Skip to content" link, a labelled navigation landmark, aria-current on the link to this page
   - visible keyboard focus everywhere; reduced motion when the system asks for it
   - dialogs: focus moves in, Tab stays inside, Escape cancels, focus returns where it was
   - names for form controls and symbol-only buttons the pages build in script
   - keyboard access (Tab + Enter/Space) for rows and tiles that only reacted to a mouse
   - charts: one Tab stop each, arrow keys between tiles/cells, tooltips on keyboard focus
   - status and error messages read out by screen readers */
(() => {
  "use strict";
  const d = document;
  const st = d.createElement("style");
  st.textContent = `.uo-skip{position:absolute;left:8px;top:-80px;z-index:1000;background:var(--surface,#fff);color:var(--ink,#111);
border:2px solid var(--accent,#2d6a4f);border-radius:6px;padding:8px 12px;font:14px system-ui,sans-serif;text-decoration:none}
.uo-skip:focus{top:8px}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible,
[tabindex]:not([tabindex="-1"]):focus-visible{outline:2px solid var(--accent,#2d6a4f);outline-offset:2px}
[tabindex="-1"]:focus{outline:none}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;
transition-duration:.01ms!important;scroll-behavior:auto!important}}`;
  d.head.appendChild(st);

  // ---- landmarks
  const hdr = d.querySelector("body > header");
  const main = d.querySelector("main, [role=main]");
  if (hdr && main && getComputedStyle(main).display !== "contents") {
    if (!main.id) main.id = "main";
    if (!main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1");
    const a = d.createElement("a");
    a.href = "#" + main.id; a.className = "uo-skip"; a.textContent = "Skip to content";
    a.addEventListener("click", e => { e.preventDefault(); main.focus(); });
    d.body.prepend(a);
  }
  if (hdr) {
    let nav = hdr.querySelector("nav");
    const loose = [...hdr.children].filter(e => e.tagName === "A" && !e.hidden);
    if (!nav && loose.length > 1) {
      nav = d.createElement("nav"); nav.style.display = "contents";
      loose[0].before(nav); loose.forEach(l => nav.appendChild(l));
    }
    if (nav && !nav.getAttribute("aria-label")) nav.setAttribute("aria-label", "Pages");
  }
  const current = () => d.querySelectorAll("body > header nav a[href]").forEach(a => {
    const here = new URL(a.href, location.href).pathname === location.pathname;
    if (here) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });

  // ---- names
  const SYMBOL = {"✕": "Close", "×": "Close", "✖": "Close", "⋯": "More", "…": "More", "⋮": "More", "←": "Back", "→": "Next",
    "‹": "Previous", "›": "Next", "+": "Add", "−": "Remove", "-": "Remove", "↑": "Move up", "↓": "Move down",
    "▸": "Expand", "▾": "Collapse", "▶": "Play", "⏸": "Pause", "↻": "Refresh", "⟳": "Refresh", "✎": "Edit", "🗑": "Delete"};
  const text = s => String(s || "").replace(/\s+/g, " ").trim();
  function nameControl(el) {
    if (el.type === "hidden" || el.getAttribute("aria-label") || el.getAttribute("aria-labelledby")) return;
    if (el.labels && [...el.labels].some(l => text(l.textContent))) return;
    let t = el.getAttribute("placeholder") || el.title || "";
    if (!t) {
      let p = el.previousSibling;
      while (p && !text(p.textContent)) p = p.previousSibling;
      t = p ? p.textContent : "";
    }
    const cell = el.closest("td");
    if (!text(t) && cell) {  // in a table: its column heading and the row's first cell ("Type – Alex")
      const th = cell.closest("table")?.querySelectorAll("thead th")[cell.cellIndex];
      const first = cell.parentElement.cells[0];
      const who = first && first !== cell ? (first.querySelector("input,select")?.value || first.textContent) : "";
      t = [th ? th.textContent : "", who].map(text).filter(Boolean).join(" – ");
    }
    if (!text(t)) {
      const row = el.closest("tr, li, .row, .gh, [role=row], div");
      if (row) { const c = row.cloneNode(true); c.querySelectorAll("select,option,script,style").forEach(x => x.remove()); t = c.textContent; }
    }
    if (!text(t) && el.name) t = el.name.replace(/[_-]+/g, " ");
    t = text(t).slice(0, 90);
    if (t) el.setAttribute("aria-label", t);
  }
  function nameButton(b) {
    if (b.getAttribute("aria-label") || b.getAttribute("aria-labelledby")) return;
    const t = text(b.textContent);
    if (/[\p{L}\p{N}]/u.test(t)) return;
    const n = b.title || SYMBOL[t] || "";
    if (n) b.setAttribute("aria-label", n);
  }

  // ---- mouse-only elements → keyboard
  const INTERACTIVE = "a[href],button,input,select,textarea,summary,label,[contenteditable],[tabindex]";
  function keyboardable(el) {
    if (el.matches(INTERACTIVE) || el.closest("a[href],button,label,svg") || el.hasAttribute("data-uo-click")) return;
    const cs = getComputedStyle(el);
    if (cs.cursor !== "pointer" || cs.display === "none") return;
    const parent = el.parentElement;
    if (parent && getComputedStyle(parent).cursor === "pointer") return;  // only the outermost clickable element
    el.setAttribute("tabindex", "0");
    el.setAttribute("data-uo-click", "");
    if (!/^T[RDH]$/.test(el.tagName) && !el.querySelector(INTERACTIVE) && !el.getAttribute("role")) el.setAttribute("role", "button");
  }
  d.addEventListener("keydown", e => {
    const t = e.target;
    if ((e.key === "Enter" || e.key === " ") && t.hasAttribute && t.hasAttribute("data-uo-click") && !e.defaultPrevented) {
      e.preventDefault(); t.click();
    }
  });

  // ---- charts: one Tab stop per chart, arrow keys move to the nearest tile/cell in that direction, Home/End,
  // Enter/Space open, and the tooltip a mouse would show appears for the focused one too
  const HINT_ID = "uo-arrows-hint";
  function charts(root) {
    const up = root.closest && root.closest("[data-arrows]");  // a tile added on its own: its chart
    const boxes = [...new Set((up ? [up] : []).concat([...root.querySelectorAll("[data-arrows]")]))];
    for (const box of boxes) {
      const items = [...box.querySelectorAll(box.dataset.arrows)];
      if (!items.length) continue;
      if (!d.getElementById(HINT_ID)) {
        const h = d.createElement("span"); h.id = HINT_ID; h.hidden = true;
        h.textContent = "Arrow keys move between items, Home and End go to the first and last, Enter opens.";
        d.body.appendChild(h);
      }
      box.setAttribute("aria-describedby", HINT_ID);
      let cur = items.find(i => i.getAttribute("tabindex") === "0" && i.dataset.uoRove) || items[0];
      items.forEach(i => { i.setAttribute("tabindex", i === cur ? "0" : "-1"); i.dataset.uoRove = "1"; });
    }
  }
  const centre = el => { const r = el.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2, r}; };
  function nearest(from, items, key) {
    const a = centre(from);
    let best = null, bestScore = Infinity;
    for (const it of items) {
      if (it === from || !it.getClientRects().length) continue;
      const b = centre(it), dx = b.x - a.x, dy = b.y - a.y;
      const ok = {ArrowRight: dx > 1, ArrowLeft: dx < -1, ArrowDown: dy > 1, ArrowUp: dy < -1}[key];
      if (!ok) continue;
      const along = key === "ArrowRight" || key === "ArrowLeft" ? Math.abs(dx) : Math.abs(dy);
      const across = key === "ArrowRight" || key === "ArrowLeft" ? Math.abs(dy) : Math.abs(dx);
      const score = along + across * 2;
      if (score < bestScore) { bestScore = score; best = it; }
    }
    return best;
  }
  function moveTo(box, from, to) {
    if (!to) return;
    from.setAttribute("tabindex", "-1"); to.setAttribute("tabindex", "0"); to.focus();
    to.scrollIntoView && to.scrollIntoView({block: "nearest", inline: "nearest"});
  }
  d.addEventListener("keydown", e => {
    const t = e.target, box = t.closest && t.closest("[data-arrows]");
    if (!box || !t.matches(box.dataset.arrows)) return;
    const items = [...box.querySelectorAll(box.dataset.arrows)];
    if (/^Arrow/.test(e.key)) { e.preventDefault(); moveTo(box, t, nearest(t, items, e.key)); }
    else if (e.key === "Home") { e.preventDefault(); moveTo(box, t, items[0]); }
    else if (e.key === "End") { e.preventDefault(); moveTo(box, t, items[items.length - 1]); }
    else if ((e.key === "Enter" || e.key === " ") && !e.defaultPrevented) { e.preventDefault(); t.click(); }
  });
  const fakeMouse = (el, type) => {
    const c = centre(el);
    el.dispatchEvent(new MouseEvent(type, {bubbles: type !== "mouseenter" && type !== "mouseleave", clientX: c.r.left + Math.min(24, c.r.width / 2), clientY: c.r.bottom - 4}));
  };
  d.addEventListener("focusin", e => {
    const t = e.target, box = t.closest && t.closest("[data-arrows]");
    if (box && t.matches(box.dataset.arrows)) {
      box.querySelectorAll(box.dataset.arrows).forEach(i => i !== t && i.setAttribute("tabindex", "-1"));
      t.setAttribute("tabindex", "0");
      if (t.matches(":focus-visible")) fakeMouse(t, "mouseenter");
    }
  });
  d.addEventListener("focusout", e => {
    const t = e.target, box = t.closest && t.closest("[data-arrows]");
    if (box && t.matches(box.dataset.arrows)) fakeMouse(t, "mouseleave");
  });

  // ---- status messages
  function live(el) {
    if (!el.id || el.getAttribute("role") || el.getAttribute("aria-live")) return;
    if (/^(err|error|.*-err)$/i.test(el.id)) el.setAttribute("role", "alert");
    else if (/^(toast|msg|message|status|note|result|saved|progress|.*-msg|.*-status)$/i.test(el.id)) {
      el.setAttribute("role", "status"); el.setAttribute("aria-live", "polite");
    }
  }

  // ---- dialogs
  const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  const shown = el => !!(el && el.isConnected && el.getClientRects().length && !el.closest("[hidden]"));
  let openDlg = null, before = null;
  function dialogs() {
    d.querySelectorAll(".shade > *, .modal").forEach(m => {
      if (!m.getAttribute("role")) { m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true"); }
    });
    const dlg = [...d.querySelectorAll('[role=dialog],[role=alertdialog]')].filter(shown).pop() || null;
    if (dlg === openDlg) return;
    if (dlg) {
      const h = dlg.querySelector("h1,h2,h3,h4");
      if (h && !dlg.getAttribute("aria-labelledby") && !dlg.getAttribute("aria-label")) {
        if (!h.id) h.id = "uo-dlg-" + Math.random().toString(36).slice(2, 8);
        dlg.setAttribute("aria-labelledby", h.id);
      }
      if (!openDlg) before = d.activeElement;
      openDlg = dlg;
      if (!dlg.contains(d.activeElement)) {
        const first = dlg.querySelector("[autofocus]") || dlg.querySelector("input:not([type=hidden]),select,textarea") || dlg.querySelector(FOCUSABLE);
        if (first) first.focus(); else { dlg.setAttribute("tabindex", "-1"); dlg.focus(); }
      }
    } else {
      openDlg = null;
      if (before && before.isConnected && shown(before)) before.focus();
      before = null;
    }
  }
  d.addEventListener("keydown", e => {
    const dlg = openDlg && shown(openDlg) ? openDlg : null;
    if (!dlg) return;
    if (e.key === "Escape" && !e.defaultPrevented) {
      const cancel = [...dlg.querySelectorAll("button")].find(b => /^(mno|no|cancel|close|x)$/i.test(b.id) ||
        /^(cancel|close|not now|no|✕|×)$/i.test(text(b.textContent)) || /close|cancel/i.test(b.getAttribute("aria-label") || ""));
      if (cancel) { e.preventDefault(); cancel.click(); }
    } else if (e.key === "Tab") {
      const f = [...dlg.querySelectorAll(FOCUSABLE)].filter(shown);
      if (!f.length) { e.preventDefault(); return; }
      const i = f.indexOf(d.activeElement);
      if (e.shiftKey && (i <= 0)) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && (i === -1 || i === f.length - 1)) { e.preventDefault(); f[0].focus(); }
    }
  });

  // ---- apply now and whenever a page changes itself
  function sweep(root) {
    if (!root.querySelectorAll) return;
    const all = sel => (root.matches(sel) ? [root] : []).concat([...root.querySelectorAll(sel)]);  // the added element too
    all("input,select,textarea").forEach(nameControl);
    all("button").forEach(nameButton);
    all("[id]").forEach(live);
    all("div,span,li,td,tr,th,section,article,p,b,i,strong,small,h3,h4").forEach(el => el.closest("[data-arrows]") ? null : keyboardable(el));
    charts(root);
  }
  let pending = new Set(), timer = 0;
  function flush() {
    timer = 0;
    const roots = [...pending]; pending = new Set();
    roots.forEach(r => r.isConnected && sweep(r));
    current(); dialogs();
  }
  new MutationObserver(ms => {
    for (const m of ms) {
      if (m.type === "childList") m.addedNodes.forEach(n => n.nodeType === 1 && pending.add(n));
      else if (m.target.nodeType === 1) pending.add(m.target);
    }
    if (!timer) timer = setTimeout(flush, 60);
  }).observe(d.body, {childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "class", "style"]});
  sweep(d.body); current(); dialogs();
})();
