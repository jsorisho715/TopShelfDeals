// Shared helpers for the TopShelf app: tilt+glare, count-up, score ring, icons, data augment.
const { useRef, useState, useEffect, useCallback } = React;

/* ---------- data augmentation: price history + score factor breakdown ---------- */
function tsAugment(deals) {
  const areaMedian = {}; // $/g median per category for "vs area" factor
  const byCat = {};
  deals.forEach(d => { (byCat[d.cat] ||= []).push(d.unit); });
  Object.keys(byCat).forEach(c => { const a = [...byCat[c]].sort((x, y) => x - y); areaMedian[c] = a[Math.floor(a.length / 2)]; });

  // a couple of deals are "markup-then-discount" traps — they should NOT earn the fire badge
  const MARKUP = new Set(['pr3', 'va3']);

  return deals.map(d => {
    // deterministic pseudo price history (trailing 14 daily observations)
    const seed = d.id.split('').reduce((a, c) => a + c.charCodeAt(0), 0);
    const isTrap = MARKUP.has(d.id);
    const hist = [];
    for (let i = 13; i >= 0; i--) {
      const wob = Math.sin((seed + i) * 1.3) * 0.05 + Math.cos((seed * 0.7 + i)) * 0.02;
      let p;
      if (isTrap) {
        // sat near sale-price for weeks, got marked UP to "orig", then "discounted" back
        if (i >= 3) p = Math.round(d.sale * (1.03 + Math.abs(wob)));
        else if (i >= 1) p = d.orig;
        else p = d.sale;
      } else {
        p = Math.round(d.orig * (1 + wob));          // normally hovers near its regular price
        if (i === 1 && d.hot) p = d.orig;            // confirmed at full price just yesterday
        if (i === 0) p = d.sale;                     // today = the drop
      }
      hist.push(p);
    }
    // ---- price memory: is today actually the lowest, and how deep vs its own average? ----
    const prior = hist.slice(0, -1);
    const priorAvg = prior.reduce((a, b) => a + b, 0) / prior.length;
    const priorMin = Math.min(...prior);
    const isLowest = d.sale <= priorMin;             // lowest price we've tracked
    const pctBelowAvg = Math.max(0, Math.round((priorAvg - d.sale) / priorAvg * 100));
    const fire = !isTrap && isLowest && pctBelowAvg >= 36;   // FIRE = validated, exceptional, record-low
    const fireReason = !d.off
      ? 'At its regular menu price — top-shelf staple'   // full-price product, not a deal
      : fire
        ? `Lowest in 14 days · ${pctBelowAvg}% under its own average`
        : isTrap
          ? `Heads-up: it sat at $${priorMin} for weeks before this “sale”`
          : `Validated drop · ${pctBelowAvg}% under its 14-day average`;

    // score factor breakdown (sums to score, transparent per FR5)
    const median = areaMedian[d.cat] || d.unit;
    const vsArea = Math.max(0, Math.min(24, Math.round((median - d.unit) / median * 60) + 8));
    const tierW = { S: 24, A: 18, B: 12 }[d.tier] || 10;
    const depth = Math.round(d.off * 0.7);
    const distPen = Math.max(2, Math.round(18 - d.dist * 2));
    const fresh = d.seen.includes('m') ? 14 : d.seen.includes('1h') ? 10 : 6;
    const raw = depth + vsArea + tierW + distPen + fresh;
    const k = d.score / raw;
    const factors = [
      { key: 'Discount depth', v: Math.round(depth * k), hint: `${d.off}% off, validated vs history` },
      { key: '$/g vs area', v: Math.round(vsArea * k), hint: `median ${'$' + median.toFixed(1)}${d.unitLabel} nearby` },
      { key: 'Brand tier', v: Math.round(tierW * k), hint: `${d.tier}-tier top-shelf` },
      { key: 'Distance', v: Math.round(distPen * k), hint: `${d.dist} mi away` },
      { key: 'Freshness', v: Math.round(fresh * k), hint: `confirmed ${d.seen}` },
    ];
    return { ...d, hist, factors, median, priorAvg, priorMin, isLowest, pctBelowAvg, fire, isTrap, fireReason };
  });
}

/* ---------- mouse-following tilt + glare (Vault A) ---------- */
function useTilt(max = 9, glareMax = 0.4) {
  const ref = useRef(null);
  const onMove = useCallback((e) => {
    const el = ref.current; if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    el.style.transform = `perspective(1000px) rotateY(${px * max}deg) rotateX(${-py * max}deg) translateZ(16px)`;
    const gl = el.querySelector('[data-glare]');
    if (gl) { gl.style.opacity = glareMax; gl.style.background = `radial-gradient(440px circle at ${(px + .5) * 100}% ${(py + .5) * 100}%, rgba(255,247,214,.5), rgba(94,255,160,.08) 35%, transparent 60%)`; }
  }, [max, glareMax]);
  const onLeave = useCallback(() => {
    const el = ref.current; if (!el) return;
    el.style.transform = 'perspective(1000px) rotateY(0) rotateX(0) translateZ(0)';
    const gl = el.querySelector('[data-glare]'); if (gl) gl.style.opacity = 0;
  }, []);
  return { ref, onMove, onLeave };
}

/* ---------- animated count-up (robust against background-tab rAF throttling) ---------- */
function useCountUp(target, dur = 1500) {
  const [v, setV] = useState(0);
  const prev = useRef(0);
  useEffect(() => {
    const from = prev.current;
    if (from === target) { setV(target); return; }
    const start = Date.now();
    const id = setInterval(() => {
      const p = Math.min((Date.now() - start) / dur, 1);
      const val = Math.round(from + (target - from) * (1 - Math.pow(1 - p, 3)));
      setV(val);
      if (p >= 1) { prev.current = target; clearInterval(id); }
    }, 33);
    // safety: guarantee the final value even if interval is throttled
    const done = setTimeout(() => { setV(target); prev.current = target; clearInterval(id); }, dur + 400);
    return () => { clearInterval(id); clearTimeout(done); };
  }, [target, dur]);
  return v;
}

/* ---------- score ring ---------- */
function ScoreRing({ score, size = 52, stroke = 4, showLabel = true }) {
  const r = (size - stroke * 2) / 2, c = 2 * Math.PI * r;
  const col = score >= 93 ? '#5effa0' : score >= 85 ? '#e8c662' : '#e0a04d';
  const off = c * (1 - score / 100);
  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,.1)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={col} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={off} style={{ filter: `drop-shadow(0 0 5px ${col}aa)`, transition: 'stroke-dashoffset 1.1s cubic-bezier(.2,.8,.2,1)' }} />
      </svg>
      {showLabel && <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: size > 48 ? 17 : 13, color: col, lineHeight: 1 }}>{score}</span>
      </div>}
    </div>
  );
}

/* ---------- sparkline for price history (with trailing-avg reference) ---------- */
function Sparkline({ data, w = 220, h = 54, sale, avg }) {
  const min = Math.min(...data), max = Math.max(...data), rng = max - min || 1;
  const y = (v) => h - 6 - ((v - min) / rng) * (h - 12);
  const pts = data.map((v, i) => [(i / (data.length - 1)) * w, y(v)]);
  const path = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  const last = pts[pts.length - 1];
  return (
    <svg width={w} height={h} style={{ display: 'block', overflow: 'visible' }}>
      <defs><linearGradient id="spk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="rgba(94,255,160,.25)" /><stop offset="1" stopColor="rgba(94,255,160,0)" /></linearGradient></defs>
      {avg != null && <g>
        <line x1="0" y1={y(avg).toFixed(1)} x2={w} y2={y(avg).toFixed(1)} stroke="rgba(232,198,98,.55)" strokeWidth="1" strokeDasharray="4 4" />
        <text x={w} y={y(avg) - 4} textAnchor="end" fill="#e8c662" fontSize="9" fontFamily="JetBrains Mono, monospace">avg ${Math.round(avg)}</text>
      </g>}
      <path d={`${path} L ${w} ${h} L 0 ${h} Z`} fill="url(#spk)" />
      <path d={path} fill="none" stroke="#5effa0" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="4" fill="#5effa0" style={{ filter: 'drop-shadow(0 0 5px #5effa0)' }} />
      <text x={last[0]} y={last[1] + 16} textAnchor="end" fill="#5effa0" fontSize="9" fontFamily="JetBrains Mono, monospace">${sale}</text>
    </svg>
  );
}

/* ---------- minimal line icons per category (functional UI, not faux photography) ---------- */
const CAT_ICON = {
  All: (p) => <svg {...p} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>,
  Flower: (p) => <svg {...p} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M12 21c0-4 0-6-3-9M12 21c0-4 0-6 3-9M12 12c-2-3-2-6 0-9 2 3 2 6 0 9zM12 12c3-2 6-2 9 0-3 2-6 2-9 0zM12 12C9 10 6 10 3 12c3 2 6 2 9 0z"/></svg>,
  Prerolls: (p) => <svg {...p} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M3 16l13-3 5-1.2M16 13l1.5 4M5 16.5l9-2"/><path d="M19.5 11.6l1.5-.4"/></svg>,
  Edibles: (p) => <svg {...p} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="4" y="8" width="16" height="12" rx="3"/><path d="M8 8V6a4 4 0 018 0v2M9 13h.01M15 13h.01M10 16h4"/></svg>,
  Concentrates: (p) => <svg {...p} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M12 3c3 4.5 5 7.2 5 10a5 5 0 11-10 0c0-2.8 2-5.5 5-10z"/></svg>,
  Vapes: (p) => <svg {...p} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="6" y="3" width="6" height="18" rx="3" transform="rotate(-30 9 12)"/><path d="M14 6.5l2.5-1.2"/></svg>,
};

/* ---------- strain palette ---------- */
function strainTone(type) {
  switch (type) {
    case 'Indica': return { a: '#4a2d6b', b: '#160d2b', glow: '#9b6dff', text: '#c9b4ff', tag: 'rgba(155,109,255,.16)', tagB: 'rgba(155,109,255,.4)' };
    case 'Sativa': return { a: '#7a4f15', b: '#241606', glow: '#ffb24d', text: '#ffd699', tag: 'rgba(255,178,77,.14)', tagB: 'rgba(255,178,77,.4)' };
    default:       return { a: '#1a5a3a', b: '#07211a', glow: '#3ddc84', text: '#9af0c4', tag: 'rgba(61,220,132,.14)', tagB: 'rgba(61,220,132,.4)' };
  }
}

/* ---------- procedural branded product shot (default visual; shows real photo if dropped) ---------- */
function ProductShot({ d, height = 150, img = null, big = false, radius = 14, children }) {
  const t = strainTone(d.type);
  const mono = d.brand.split(' ').map(w => w[0]).join('').slice(0, 2);
  // Prefer a dropped photo, otherwise the deal's own scraped product image.
  const shownImg = img || (d && d.img) || null;
  return (
    <div style={{ position: 'relative', height, borderRadius: radius, overflow: 'hidden', flexShrink: 0,
      background: `radial-gradient(120% 110% at 28% 8%, ${t.a} 0%, ${t.b} 62%, #060d09 100%)` }}>
      {/* ambient strain glow */}
      <div style={{ position: 'absolute', width: '70%', height: '120%', left: '-10%', top: '-25%', borderRadius: '50%',
        background: `radial-gradient(circle, ${t.glow}33, transparent 65%)`, filter: 'blur(8px)' }} />
      {/* big translucent monogram (brand) */}
      {!shownImg && <div style={{ position: 'absolute', right: big ? 24 : 12, bottom: big ? -14 : -10,
        fontFamily: 'Clash Display, sans-serif', fontWeight: 700, fontSize: big ? 168 : height * 0.92,
        color: 'rgba(255,255,255,.07)', letterSpacing: '-.05em', lineHeight: 1, userSelect: 'none' }}>{mono}</div>}
      {/* real product photo (scraped img, or a dropped one) */}
      {shownImg && <img src={shownImg} alt={d.product} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />}
      {/* sheen */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '40%', background: 'linear-gradient(180deg, rgba(255,255,255,.09), transparent)', pointerEvents: 'none' }} />
      {/* category glyph + strain tag */}
      {!shownImg && <div style={{ position: 'absolute', top: 10, left: 10, display: 'flex', alignItems: 'center', gap: 7, color: t.text }}>
        {React.createElement(CAT_ICON[d.cat] || CAT_ICON.All, { width: big ? 22 : 18, height: big ? 22 : 18, style: { opacity: .9 } })}
      </div>}
      <div style={{ position: 'absolute', bottom: 10, left: 10, display: 'flex', gap: 6 }}>
        <span style={{ fontSize: big ? 11 : 10, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase',
          color: t.text, background: t.tag, border: `1px solid ${t.tagB}`, padding: '3px 9px', borderRadius: 20, backdropFilter: 'blur(4px)' }}>{d.type}</span>
        {d.thc >= 1 && d.unitLabel !== '/10mg' && <span style={{ fontSize: big ? 11 : 10, fontWeight: 700, letterSpacing: '.04em',
          color: '#f3ede0', background: 'rgba(0,0,0,.4)', border: '1px solid rgba(255,255,255,.18)', padding: '3px 9px', borderRadius: 20, backdropFilter: 'blur(4px)' }}>{d.thc}% THC</span>}
      </div>
      {children}
    </div>
  );
}

/* ---------- read user-dropped photos from the image-slot sidecar ---------- */
function useImageSlots(refreshKey) {
  const [map, setMap] = useState({});
  useEffect(() => {
    let alive = true;
    fetch('.image-slots.state.json').then(r => r.ok ? r.json() : {}).then(j => {
      if (!alive || !j) return;
      const m = {};
      Object.keys(j).forEach(k => { const v = j[k]; const u = typeof v === 'string' ? v : (v && v.u); if (u) m[k] = u; });
      setMap(m);
    }).catch(() => {});
    return () => { alive = false; };
  }, [refreshKey]);
  return map;
}

/* ---------- location / link helpers ---------- */
function getDist(d, locId) {
  const t = (window.TS_DIST[locId] || window.TS_DIST.oldtown);
  return t[d.shop] != null ? t[d.shop] : d.dist;
}
function mapsDirUrl(shop) {
  const s = window.TS_SHOPS[shop];
  return 'https://www.google.com/maps/dir/?api=1&destination=' + encodeURIComponent(s ? s.addr : shop);
}
function menuFor(shop) {
  const s = window.TS_SHOPS[shop];
  return s ? s.menu : '#';
}
// Deep link to the actual special when the deal has one; else the shop's menu.
function specialFor(d) {
  return (d && d.url) ? d.url : menuFor(d && d.shop);
}
function platformFor(shop) {
  const s = window.TS_SHOPS[shop];
  return s ? s.platform : 'menu';
}

Object.assign(window, { tsAugment, useTilt, useCountUp, ScoreRing, Sparkline, CAT_ICON, strainTone, ProductShot, useImageSlots, getDist, mapsDirUrl, menuFor, specialFor, platformFor });
