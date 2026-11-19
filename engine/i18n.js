/* Page language. The server puts window.UO_I18N = {lang, dict, languages:[{code,name}]} before this script.
   Every text the page shows (markup, text its scripts add later, placeholders, titles, aria-labels, alerts and
   confirmations) is looked up in the dictionary: exact texts, then patterns with {0}, {1}… for numbers and names.
   Anything not in the dictionary stays in English. Names of files, people and folders are never in the dictionary,
   so they are never changed. A "Language" picker is added to the page header; the choice is kept per device. */
(() => {
  "use strict";
  const C = window.UO_I18N || {lang: "en", dict: {}, languages: []};
  const d = document;
  const exact = new Map(), pats = [];
  let longest = 0;
  const norm = s => s.replace(/\s+/g, " ").trim();
  for (const [k, v] of Object.entries(C.dict || {})) {
    if (k[0] === "_" || typeof v !== "string") continue;
    longest = Math.max(longest, k.length);
    if (/\{\d+\}/.test(k)) {
      const order = [];
      const lits = k.split(/\{\d+\}/).filter(Boolean);
      const rx = k.split(/(\{\d+\})/).map(p => {
        const m = /^\{(\d+)\}$/.exec(p);
        if (m) { order.push(+m[1]); return "(.{1,160}?)"; }  // bounded: no runaway matching on long text
        return p.replace(/[.*+?^$()|[\]\\{}]/g, "\\$&");
      }).join("");
      pats.push({rx: new RegExp("^" + rx + "$", "s"), order, v, lits, weight: k.replace(/\{\d+\}/g, "").length});
    } else exact.set(k, v);
  }
  pats.sort((a, b) => b.weight - a.weight);

  function tr(text) {
    if (!text || text.length > longest + 400) return null;  // document text, not page text
    const n = norm(text);
    if (!n || !/[A-Za-z]/.test(n)) return null;
    let out = exact.get(n);
    if (out === undefined) {
      for (const p of pats) {
        let at = 0, ok = true;  // cheap check first: the fixed words appear, in order
        for (const l of p.lits) { const i = n.indexOf(l, at); if (i < 0) { ok = false; break; } at = i + l.length; }
        if (!ok) continue;
        const m = p.rx.exec(n);
        if (m) {
          const vals = {};
          p.order.forEach((idx, i) => { vals[idx] = m[i + 1]; });
          out = p.v.replace(/\{(\d+)\}/g, (_, i) => vals[i] ?? "");
          break;
        }
      }
    }
    if (out === undefined) {  // "📁 Identity documents", "✂ Cut": a symbol in front, the text after it
      const m = /^([^\p{L}\p{N}(“"']+)(\p{L}.*)$/su.exec(n);
      const rest = m && tr(m[2]);
      if (!rest) return null;
      out = m[1] + rest.trim();
    }
    const lead = /^\s*/.exec(text)[0], trail = /\s*$/.exec(text)[0];
    return lead + out + trail;
  }
  function trLong(msg) {  // alerts and confirmations: whole text, else line by line, else sentence by sentence
    const s = String(msg ?? "");
    const whole = tr(s);
    if (whole) return whole;
    return s.split("\n").map(line => tr(line) || line.split(/(?<=[.!?])\s+/).map(x => tr(x) || x).join(" ")).join("\n");
  }
  window.uoT = trLong;  // for pages that want to translate a message themselves

  if (C.lang !== "en" && (exact.size || pats.length)) {
    const SKIP = new Set(["SCRIPT", "STYLE", "CODE", "PRE", "TEXTAREA", "KBD", "SAMP"]);
    const ATTRS = ["placeholder", "title", "aria-label", "alt"];
    const done = new WeakMap();
    const skip = el => !el || SKIP.has(el.tagName) || (el.closest && el.closest("[data-no-i18n],[contenteditable]"));
    function textNode(n) {
      if (done.get(n) === n.nodeValue || skip(n.parentElement)) return;
      const t = tr(n.nodeValue);
      if (t !== null && t !== n.nodeValue) n.nodeValue = t;
      done.set(n, n.nodeValue);
    }
    function attrs(el) {
      if (skip(el)) return;
      for (const a of ATTRS) {
        const v = el.getAttribute(a);
        if (v) { const t = tr(v); if (t !== null && t !== v) el.setAttribute(a, t); }
      }
      if (el.tagName === "INPUT" && /^(button|submit|reset)$/.test(el.type) && el.value) {
        const t = tr(el.value); if (t && t !== el.value) el.value = t;
      }
    }
    function walk(root) {
      if (root.nodeType === 3) return textNode(root);
      if (root.nodeType !== 1 || skip(root)) return;
      attrs(root);
      const w = d.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
        acceptNode: n => n.nodeType === 1 && SKIP.has(n.tagName) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT});
      for (let n = w.nextNode(); n; n = w.nextNode()) n.nodeType === 3 ? textNode(n) : attrs(n);
    }
    new MutationObserver(ms => {
      for (const m of ms) {
        if (m.type === "childList") m.addedNodes.forEach(walk);
        else if (m.type === "characterData") textNode(m.target);
        else if (m.type === "attributes") attrs(m.target);
      }
    }).observe(d.documentElement, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS});
    const titleT = () => { const t = tr(d.title); if (t && t !== d.title) d.title = t; };  // same text: leave it (no loop)
    d.addEventListener("DOMContentLoaded", () => { walk(d.body); titleT(); });
    new MutationObserver(titleT).observe(d.head || d.documentElement, {childList: true, subtree: true, characterData: true});
    for (const f of ["alert", "confirm", "prompt"]) {
      const orig = window[f].bind(window);
      window[f] = (msg, ...rest) => orig(trLong(msg), ...rest);
    }
    d.documentElement.lang = C.lang;
  }

  // ---- the picker: in the header, or in a corner on pages without one (sign-in)
  if ((C.languages || []).length > 1) {
    d.addEventListener("DOMContentLoaded", () => {
      const sel = d.createElement("select");
      sel.setAttribute("aria-label", tr("Language") || "Language");
      sel.setAttribute("data-no-i18n", "");
      sel.style.cssText = "font:12.5px var(--f,system-ui);border:1px solid var(--line,#ccc);background:var(--surface,#fff);color:var(--ink,#111);border-radius:6px;padding:3px 6px";
      for (const l of C.languages) {
        const o = d.createElement("option"); o.value = l.code; o.textContent = l.name; o.selected = l.code === C.lang; sel.appendChild(o);
      }
      sel.onchange = () => {
        d.cookie = `uo_lang=${encodeURIComponent(sel.value)}; Path=/; Max-Age=31536000; SameSite=Strict${location.protocol === "https:" ? "; Secure" : ""}`;
        location.reload();
      };
      const hdr = d.querySelector("body > header");
      if (hdr) hdr.appendChild(sel);
      else { sel.style.position = "fixed"; sel.style.top = "10px"; sel.style.right = "10px"; sel.style.zIndex = "50"; d.body.appendChild(sel); }
    });
  }
})();
