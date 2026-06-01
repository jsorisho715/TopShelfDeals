// Web dashboard view — Gallery-depth glass cards w/ Vault tilt+glare, tabs, filters, hero spotlight.
const { useState: dbUseState, useMemo: dbUseMemo } = React;

function GlassCard({ d, onOpen, onPing, pinged, photo, loc }) {
  const tilt = window.useTilt(8, 0.42);
  const [hov, setHov] = dbUseState(false);
  const accent = d.score >= 93 ? '#5effa0' : '#e8c662';
  const dist = window.getDist(d, loc);
  return (
    <div onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)} style={{ transformStyle: 'preserve-3d' }}>
      <div ref={tilt.ref} onMouseMove={tilt.onMove} onMouseLeave={tilt.onLeave} onClick={() => onOpen(d)} style={{
        position: 'relative', borderRadius: 20, padding: 0, cursor: 'pointer', transformStyle: 'preserve-3d', overflow: 'hidden',
        background: 'linear-gradient(160deg, rgba(34,56,42,.55), rgba(12,24,17,.66))',
        backdropFilter: 'blur(14px) saturate(140%)', WebkitBackdropFilter: 'blur(14px) saturate(140%)',
        border: '1px solid ' + (hov ? 'rgba(212,175,55,.4)' : 'rgba(255,255,255,.1)'),
        boxShadow: hov ? '0 44px 70px -26px rgba(0,0,0,.92), 0 1px 0 rgba(255,255,255,.14) inset' : '0 22px 40px -26px rgba(0,0,0,.85), 0 1px 0 rgba(255,255,255,.08) inset',
        transition: 'box-shadow .25s, border-color .25s', display: 'flex', flexDirection: 'column', minHeight: 196,
      }}>
        <div data-glare style={{ position: 'absolute', inset: 0, borderRadius: 20, opacity: 0, transition: 'opacity .25s', pointerEvents: 'none', zIndex: 5 }} />

        {/* product image */}
        <div style={{ position: 'relative', transform: 'translateZ(8px)' }}>
          <window.ProductShot d={d} img={photo} height={132} radius={0} />
          <div style={{ position: 'absolute', top: 10, right: 10 }}><window.ScoreRing score={d.score} size={44} /></div>
          <div style={{ position: 'absolute', top: 12, left: 'auto', right: 'auto' }} />
          <div style={{ position: 'absolute', top: 44, left: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {d.fire && <span style={dbHot}>🔥 FIRE</span>}
            {!d.fire && d.off > 0 && <span style={dbDeal}>−{d.off}% DEAL</span>}
            {d.provisional && !d.fire && <span style={dbTrack}>◷ TRACKING</span>}
            {d.isTrap && <span style={dbWarn}>⚠ MARKUP</span>}
            {d.recurring && <span style={dbRecur}>↻ {d.dow}</span>}
            {!d.stock && <span style={dbStale}>SOLD OUT</span>}
            {d.stale && d.stock && <span style={dbStaleBadge}>STALE</span>}
          </div>
        </div>

        <div style={{ padding: '14px 16px 16px', display: 'flex', flexDirection: 'column', gap: 11, flex: 1 }}>
        <div style={{ transform: 'translateZ(26px)' }}>
          <div style={{ color: '#e8c662', fontSize: 12, fontWeight: 600, letterSpacing: '.05em' }}>{d.brand}</div>
          <div style={{ fontFamily: 'Clash Display, sans-serif', fontWeight: 600, color: '#f3ede0', fontSize: 21, lineHeight: 1.03, marginTop: 2, letterSpacing: '-.01em' }}>{d.product}</div>
        </div>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 9, transform: 'translateZ(18px)' }}>
          <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 30, color: '#fff' }}>${d.sale}</span>
          {d.off > 0 ? (
            <React.Fragment>
              <span style={{ color: '#6f8576', textDecoration: 'line-through', fontSize: 14 }}>${d.orig}</span>
              <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 17, color: accent, textShadow: `0 0 14px ${accent}66`, marginLeft: 2 }}>−{d.off}%</span>
            </React.Fragment>
          ) : (
            <span style={{ fontSize: 11, color: '#8aa394', fontWeight: 600, letterSpacing: '.04em' }}>Menu price</span>
          )}
          <span style={{ marginLeft: 'auto', fontSize: 11.5, color: '#bcd3c4', background: 'rgba(255,255,255,.06)', padding: '3px 9px', borderRadius: 20, border: '1px solid rgba(255,255,255,.1)' }}>${d.unit.toFixed(1)}{d.unitLabel}</span>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 11, marginTop: 'auto', borderTop: '1px solid rgba(255,255,255,.08)', fontSize: 11.5, color: '#8aa394', transform: 'translateZ(10px)' }}>
          <span>{d.shop} · {dist} mi</span>
          <button onClick={(e) => { e.stopPropagation(); onPing(d); }} title="Send to Telegram" style={{
            display: 'flex', alignItems: 'center', gap: 5, border: '1px solid ' + (pinged ? 'rgba(94,255,160,.5)' : 'rgba(255,255,255,.14)'),
            background: pinged ? 'rgba(94,255,160,.14)' : 'rgba(255,255,255,.04)', color: pinged ? '#5effa0' : '#cbd8cc',
            borderRadius: 20, padding: '4px 10px', fontSize: 11, fontFamily: 'Satoshi', cursor: 'pointer', fontWeight: 600 }}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
            {pinged ? 'Sent' : 'Ping'}
          </button>
        </div>
        </div>
      </div>
    </div>
  );
}
const dbHot = { fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', color: '#fff', background: 'linear-gradient(135deg,#ff7a3d,#e0322f)', padding: '3px 7px', borderRadius: 5, boxShadow: '0 0 12px rgba(255,90,40,.5)' };
const dbDeal = { fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', color: '#0a1610', background: 'linear-gradient(135deg,#e8c662,#b8902e)', padding: '3px 7px', borderRadius: 5 };
const dbWarn = { fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', color: '#1a1205', background: 'linear-gradient(135deg,#f0b44a,#c98a1e)', padding: '3px 7px', borderRadius: 5 };
const dbRecur = { fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', color: '#0a1610', background: 'linear-gradient(135deg,#e8c662,#b8902e)', padding: '3px 7px', borderRadius: 5 };
const dbStale = { fontSize: 9.5, fontWeight: 700, letterSpacing: '.1em', color: '#f3ede0', background: 'rgba(0,0,0,.5)', border: '1px solid rgba(255,255,255,.25)', padding: '2px 7px', borderRadius: 5 };
const dbStaleBadge = { fontSize: 9.5, fontWeight: 700, letterSpacing: '.08em', color: '#d9c38a', background: 'rgba(212,175,55,.12)', border: '1px solid rgba(212,175,55,.35)', padding: '2px 7px', borderRadius: 5 };
const dbTrack = { fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', color: '#9fc2ff', background: 'rgba(120,170,255,.12)', border: '1px solid rgba(120,170,255,.35)', padding: '3px 7px', borderRadius: 5 };

// ---- Sortable table layout -------------------------------------------------
// Columns the table can sort by. `num` columns default to descending (best first).
const TBL_COLS = [
  { key: 'rank',    label: '#',       sortable: false, align: 'center', w: 40 },
  { key: 'product', label: 'Product', align: 'left' },
  { key: 'type',    label: 'Type',    align: 'left' },
  { key: 'thc',     label: 'THC',     align: 'right', num: true },
  { key: 'unit',    label: '$/unit',  align: 'right', num: true },
  { key: 'price',   label: 'Price',   align: 'right', num: true },
  { key: 'off',     label: '% off',   align: 'right', num: true },
  { key: 'score',   label: 'Score',   align: 'center', num: true },
  { key: 'shop',    label: 'Shop',    align: 'left' },
  { key: 'dist',    label: 'Mi',      align: 'right', num: true },
  { key: 'ping',    label: '',        sortable: false, align: 'center', w: 64 },
];

function TableRow({ d, rank, onOpen, onPing, pinged, loc }) {
  const [hov, setHov] = dbUseState(false);
  const accent = d.score >= 93 ? '#5effa0' : '#e8c662';
  const dist = window.getDist(d, loc);
  const cell = { padding: '11px 12px', fontSize: 13, color: '#dfe8e0', borderBottom: '1px solid rgba(255,255,255,.06)', whiteSpace: 'nowrap' };
  return (
    <tr onClick={() => onOpen(d)} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ cursor: 'pointer', background: hov ? 'rgba(212,175,55,.06)' : 'transparent', transition: 'background .15s' }}>
      <td style={{ ...cell, textAlign: 'center', color: '#7e9384', fontFamily: 'JetBrains Mono', fontSize: 12 }}>{rank}</td>
      <td style={{ ...cell, whiteSpace: 'normal', minWidth: 180 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {d.fire && <span title="Fire deal" style={{ fontSize: 12 }}>🔥</span>}
          <div style={{ minWidth: 0 }}>
            <div style={{ fontFamily: 'Clash Display', fontWeight: 600, fontSize: 14.5, color: '#f3ede0', lineHeight: 1.1 }}>{d.product}</div>
            <div style={{ color: '#e8c662', fontSize: 11, fontWeight: 600, letterSpacing: '.03em', marginTop: 1 }}>{d.brand}{d.size ? ' · ' + d.size : ''}</div>
          </div>
        </div>
      </td>
      <td style={{ ...cell, color: '#9fb3a4' }}>{d.type || '—'}</td>
      <td style={{ ...cell, textAlign: 'right', fontFamily: 'JetBrains Mono', fontSize: 12.5 }}>{d.thc != null ? d.thc + '%' : '—'}</td>
      <td style={{ ...cell, textAlign: 'right', fontFamily: 'JetBrains Mono', fontSize: 12.5 }}>{d.unit != null ? '$' + d.unit.toFixed(1) + d.unitLabel : '—'}</td>
      <td style={{ ...cell, textAlign: 'right' }}>
        <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 15, color: '#fff' }}>${d.sale}</span>
        {d.orig > d.sale && <span style={{ color: '#6f8576', textDecoration: 'line-through', fontSize: 11.5, marginLeft: 6 }}>${d.orig}</span>}
      </td>
      <td style={{ ...cell, textAlign: 'right', fontFamily: 'Clash Display', fontWeight: 700, fontSize: 14, color: accent }}>{d.off ? '−' + d.off + '%' : '—'}</td>
      <td style={{ ...cell, textAlign: 'center' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', minWidth: 34, padding: '3px 8px', borderRadius: 9, fontFamily: 'JetBrains Mono', fontWeight: 600, fontSize: 12.5,
          color: accent, background: accent === '#5effa0' ? 'rgba(94,255,160,.1)' : 'rgba(232,198,98,.1)', border: '1px solid ' + (accent === '#5effa0' ? 'rgba(94,255,160,.3)' : 'rgba(232,198,98,.3)') }}>{d.score}</span>
      </td>
      <td style={{ ...cell, color: '#bcd3c4', whiteSpace: 'normal', minWidth: 110 }}>{d.shop}</td>
      <td style={{ ...cell, textAlign: 'right', fontFamily: 'JetBrains Mono', fontSize: 12.5, color: '#9fb3a4' }}>{dist}</td>
      <td style={{ ...cell, textAlign: 'center' }}>
        <button onClick={(e) => { e.stopPropagation(); onPing(d); }} title="Send to Telegram" style={{
          display: 'inline-flex', alignItems: 'center', gap: 4, border: '1px solid ' + (pinged ? 'rgba(94,255,160,.5)' : 'rgba(255,255,255,.14)'),
          background: pinged ? 'rgba(94,255,160,.14)' : 'rgba(255,255,255,.04)', color: pinged ? '#5effa0' : '#cbd8cc',
          borderRadius: 18, padding: '4px 9px', fontSize: 11, fontFamily: 'Satoshi', cursor: 'pointer', fontWeight: 600 }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
          {pinged ? 'Sent' : 'Ping'}
        </button>
      </td>
    </tr>
  );
}

function DealTable({ rows, onOpen, onPing, pingedIds, loc, tSort, onSort }) {
  return (
    <div style={{ overflowX: 'auto', borderRadius: 16, border: '1px solid rgba(255,255,255,.08)', background: 'rgba(255,255,255,.022)',
      boxShadow: '0 22px 40px -30px rgba(0,0,0,.85)', WebkitOverflowScrolling: 'touch' }}>
      <table style={{ width: '100%', minWidth: 760, borderCollapse: 'collapse', fontFamily: 'Satoshi' }}>
        <thead>
          <tr>
            {TBL_COLS.map(col => {
              const on = tSort.key === col.key;
              return (
                <th key={col.key} onClick={() => col.sortable !== false && onSort(col.key)}
                  style={{ position: 'sticky', top: 0, zIndex: 1, padding: '12px 12px', textAlign: col.align, width: col.w,
                    fontSize: 10.5, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', whiteSpace: 'nowrap',
                    color: on ? '#f1dd9e' : '#8aa394', cursor: col.sortable === false ? 'default' : 'pointer', userSelect: 'none',
                    background: 'linear-gradient(180deg, rgba(16,30,21,.98), rgba(13,25,17,.98))',
                    borderBottom: '1px solid rgba(212,175,55,.22)' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, justifyContent: col.align === 'right' ? 'flex-end' : col.align === 'center' ? 'center' : 'flex-start' }}>
                    {col.label}
                    {on && <span style={{ fontSize: 9, color: '#e8c662' }}>{tSort.dir === 'asc' ? '▲' : '▼'}</span>}
                  </span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((d, i) => (
            <TableRow key={d.id} d={d} rank={i + 1} onOpen={onOpen} onPing={onPing} pinged={pingedIds.has(d.id)} loc={loc} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Full filter-criteria shape; 0 on a cap means "no limit".
const FILTER_DEFAULTS = { cat: 'All', sort: 'score', maxDist: 20, minOff: 0, inStock: true,
  brands: [], strains: [], minThc: 0, maxUnit: 0, maxPrice: 0, tiers: [], shops: [], fireOnly: false, saleOnly: false };
const normC = (c) => ({ ...FILTER_DEFAULTS, ...(c || {}) });

const DEFAULT_PRESETS = [
  { id: 'everyday', name: 'Everyday top-shelf', c: { cat: 'All', sort: 'score', maxDist: 20, minOff: 0, inStock: true } },
  { id: 'fireflower', name: 'Fire flower', c: { cat: 'Flower', sort: 'off', maxDist: 20, minOff: 30, inStock: true } },
  { id: 'cheapdabs', name: 'Cheap dabs', c: { cat: 'Concentrates', sort: 'price', maxDist: 20, minOff: 0, inStock: true } },
];
function loadPresets() {
  try { const j = JSON.parse(localStorage.getItem('ts_presets')); if (Array.isArray(j) && j.length) return j; } catch (e) {}
  return DEFAULT_PRESETS;
}

function Dashboard({ deals, onOpen, onPing, pingedIds, photos = {}, loc, setLoc }) {
  const [presets, setPresets] = dbUseState(loadPresets);
  const [active, setActive] = dbUseState(() => localStorage.getItem('ts_active') || 'everyday');
  const init = normC((presets.find(p => p.id === active) || presets[0]).c);
  const [cat, setCat] = dbUseState(init.cat);
  const [sort, setSort] = dbUseState(init.sort);
  const [maxDist, setMaxDist] = dbUseState(init.maxDist);
  const [minOff, setMinOff] = dbUseState(init.minOff);
  const [inStock, setInStock] = dbUseState(init.inStock);
  const [brands, setBrands] = dbUseState(init.brands);
  const [strains, setStrains] = dbUseState(init.strains);
  const [minThc, setMinThc] = dbUseState(init.minThc);
  const [maxUnit, setMaxUnit] = dbUseState(init.maxUnit);
  const [maxPrice, setMaxPrice] = dbUseState(init.maxPrice);
  const [tiers, setTiers] = dbUseState(init.tiers);
  const [shops, setShops] = dbUseState(init.shops);
  const [fireOnly, setFireOnly] = dbUseState(init.fireOnly);
  const [saleOnly, setSaleOnly] = dbUseState(init.saleOnly);
  const [showFilters, setShowFilters] = dbUseState(false);
  const [locOpen, setLocOpen] = dbUseState(false);
  const [groupByShop, setGroupByShop] = dbUseState(false);
  const [q, setQ] = dbUseState('');
  const [layout, setLayoutState] = dbUseState(() => localStorage.getItem('ts_layout') || 'cards');
  const setLayout = (v) => { setLayoutState(v); try { localStorage.setItem('ts_layout', v); } catch (e) {} };
  const [tSort, setTSort] = dbUseState({ key: 'score', dir: 'desc' });
  const onTableSort = (key) => setTSort(s => s.key === key
    ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
    : { key, dir: (key === 'product' || key === 'brand' || key === 'shop' || key === 'type') ? 'asc' : 'desc' });

  const current = { cat, sort, maxDist, minOff, inStock, brands, strains, minThc, maxUnit, maxPrice, tiers, shops, fireOnly, saleOnly };
  const matchesActive = dbUseMemo(() => {
    const p = presets.find(x => x.id === active);
    return p && JSON.stringify(normC(p.c)) === JSON.stringify(current);
  }, [presets, active, current]);

  // toggle helper for chip multi-selects
  const toggleIn = (arr, setArr, v) => setArr(arr.includes(v) ? arr.filter(x => x !== v) : [...arr, v]);

  const applyPreset = (p) => {
    setActive(p.id); localStorage.setItem('ts_active', p.id);
    const c = normC(p.c);
    setCat(c.cat); setSort(c.sort); setMaxDist(c.maxDist); setMinOff(c.minOff); setInStock(c.inStock);
    setBrands(c.brands); setStrains(c.strains); setMinThc(c.minThc); setMaxUnit(c.maxUnit); setMaxPrice(c.maxPrice);
    setTiers(c.tiers); setShops(c.shops); setFireOnly(c.fireOnly); setSaleOnly(c.saleOnly);
  };
  const saveCurrent = () => {
    const name = (prompt('Name this filter', cat === 'All' ? 'My filter' : cat + ' deals') || '').trim();
    if (!name) return;
    const np = { id: 'p' + Date.now(), name, c: { ...current } };
    const next = [...presets, np]; setPresets(next); setActive(np.id);
    try { localStorage.setItem('ts_presets', JSON.stringify(next)); localStorage.setItem('ts_active', np.id); } catch (e) {}
  };
  const removePreset = (id) => {
    const next = presets.filter(p => p.id !== id); setPresets(next);
    try { localStorage.setItem('ts_presets', JSON.stringify(next)); } catch (e) {}
    if (active === id && next[0]) applyPreset(next[0]);
  };

  // option lists for the multi-selects (derived from the live deals)
  const brandOptions = dbUseMemo(() => [...new Set(deals.map(d => d.brand).filter(Boolean))].sort(), [deals]);
  const shopOptions = dbUseMemo(() => [...new Set(deals.map(d => d.shop).filter(Boolean))].sort(), [deals]);

  const filtered = dbUseMemo(() => {
    const needle = q.trim().toLowerCase();
    const matchQ = (d) => !needle || [d.product, d.brand, d.shop, d.lineage, d.type, d.area]
      .some(v => (v || '').toLowerCase().includes(needle));
    let r = deals.filter(d =>
      (cat === 'All' || d.cat === cat) &&
      window.getDist(d, loc) <= maxDist &&
      d.off >= minOff &&
      (!inStock || d.stock) &&
      (brands.length === 0 || brands.includes(d.brand)) &&
      (strains.length === 0 || strains.includes(d.type)) &&
      (minThc <= 0 || (d.thc || 0) >= minThc) &&
      (maxUnit <= 0 || (d.unit || 0) <= maxUnit) &&
      (maxPrice <= 0 || (d.sale || 0) <= maxPrice) &&
      (tiers.length === 0 || tiers.includes(d.tier)) &&
      (shops.length === 0 || shops.includes(d.shop)) &&
      (!fireOnly || d.fire) &&
      (!saleOnly || d.off > 0) &&
      matchQ(d));
    const cmp = { score: (a, b) => b.score - a.score, price: (a, b) => a.sale - b.sale, off: (a, b) => b.off - a.off, dist: (a, b) => window.getDist(a, loc) - window.getDist(b, loc) };
    return r.sort(cmp[sort]);
  }, [deals, cat, sort, maxDist, minOff, inStock, brands, strains, minThc, maxUnit, maxPrice, tiers, shops, fireOnly, saleOnly, q, loc]);

  const hero = filtered[0];
  const rest = filtered.slice(1);
  const dealCount = dbUseMemo(() => filtered.filter(d => d.off > 0).length, [filtered]);

  // Group by shop, nearest -> furthest; specials ranked best -> worst within each shop.
  const shopGroups = dbUseMemo(() => {
    const byShop = {};
    filtered.forEach(d => { (byShop[d.shop] || (byShop[d.shop] = [])).push(d); });
    const groups = Object.keys(byShop).map(shop => {
      const items = byShop[shop].slice().sort((a, b) => b.score - a.score);
      return { shop, items, dist: window.getDist(items[0], loc) };
    });
    groups.sort((a, b) => a.dist - b.dist);
    return groups;
  }, [filtered, loc]);

  // Independently sortable rows for the table layout (clickable column headers).
  const tableRows = dbUseMemo(() => {
    const get = {
      score: d => d.score, price: d => d.sale, off: d => d.off, unit: d => d.unit || 0, thc: d => d.thc || 0,
      dist: d => window.getDist(d, loc), product: d => d.product || '', type: d => d.type || '', shop: d => d.shop || '',
    }[tSort.key] || (d => d.score);
    const arr = filtered.slice().sort((a, b) => {
      const va = get(a), vb = get(b);
      const c = typeof va === 'string' ? va.localeCompare(vb) : (va - vb);
      return tSort.dir === 'asc' ? c : -c;
    });
    return arr;
  }, [filtered, tSort, loc]);

  const Icon = (c) => window.CAT_ICON[c] || window.CAT_ICON.All;
  const locObj = window.TS_LOCATIONS.find(l => l.id === loc) || window.TS_LOCATIONS[0];

  return (
    <div style={{ padding: '8px 0 60px' }}>
      {/* context bar: location + saved filters */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '14px 0 6px' }}>
        {/* location switcher */}
        <div style={{ position: 'relative' }}>
          <button onClick={() => setLocOpen(v => !v)} style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '9px 14px', borderRadius: 12, cursor: 'pointer',
            border: '1px solid rgba(212,175,55,.3)', background: 'rgba(212,175,55,.08)', color: '#f1dd9e', fontFamily: 'Satoshi', fontWeight: 600, fontSize: 13.5 }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 21s-7-6.3-7-11a7 7 0 0114 0c0 4.7-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/></svg>
            <span>{locObj.label} <span style={{ color: '#bca35e', fontWeight: 500 }}>· {locObj.sub}</span></span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" style={{ opacity: .7 }}><path d="M6 9l6 6 6-6"/></svg>
          </button>
          {locOpen && (
            <div style={{ position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 30, minWidth: 230, padding: 6, borderRadius: 14,
              background: 'rgba(16,30,21,.98)', border: '1px solid rgba(212,175,55,.25)', boxShadow: '0 30px 60px -20px rgba(0,0,0,.9)' }}>
              <div style={{ fontSize: 10.5, color: '#7e9384', letterSpacing: '.1em', textTransform: 'uppercase', padding: '8px 10px 6px' }}>Measure distance from</div>
              {window.TS_LOCATIONS.map(l => {
                const on = l.id === loc;
                return (
                  <button key={l.id} onClick={() => { setLoc(l.id); setLocOpen(false); }} style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%', textAlign: 'left',
                    padding: '10px 10px', borderRadius: 10, border: 'none', cursor: 'pointer', background: on ? 'rgba(212,175,55,.14)' : 'transparent', color: '#e9f1ea', fontFamily: 'Satoshi', fontSize: 13.5 }}>
                    <span style={{ fontSize: 15 }}>{l.icon}</span>
                    <span style={{ flex: 1 }}><b style={{ fontWeight: 600 }}>{l.label}</b> <span style={{ color: '#8aa394' }}>· {l.sub}</span></span>
                    {on && <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#e8c662" strokeWidth="2.6"><path d="M20 6L9 17l-5-5"/></svg>}
                  </button>
                );
              })}
              <button onClick={() => { alert('In the real app this would request your browser location (geolocation) and compute live straight-line distance.'); setLocOpen(false); }}
                style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%', textAlign: 'left', padding: '10px', borderRadius: 10, border: 'none', cursor: 'pointer', background: 'transparent', color: '#9fc2ff', fontFamily: 'Satoshi', fontSize: 13 }}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>Use my current location
              </button>
            </div>
          )}
        </div>

        <div style={{ width: 1, height: 22, background: 'rgba(255,255,255,.1)' }} />

        {/* saved filters */}
        <span style={{ fontSize: 12, color: '#8aa394', fontWeight: 600 }}>Saved</span>
        <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', alignItems: 'center' }}>
          {presets.map(p => {
            const on = active === p.id && matchesActive;
            return (
              <span key={p.id} style={{ display: 'inline-flex', alignItems: 'center', borderRadius: 11, overflow: 'hidden',
                border: '1px solid ' + (on ? 'transparent' : 'rgba(255,255,255,.12)'), background: on ? 'linear-gradient(135deg,#e8c662,#b8902e)' : 'rgba(255,255,255,.03)' }}>
                <button onClick={() => applyPreset(p)} style={{ padding: '7px 11px', border: 'none', cursor: 'pointer', background: 'transparent',
                  color: on ? '#0a1610' : '#cbd8cc', fontFamily: 'Satoshi', fontWeight: 600, fontSize: 12.5 }}>
                  {on && '✓ '}{p.name}
                </button>
                {!DEFAULT_PRESETS.some(d => d.id === p.id) && (
                  <button onClick={() => removePreset(p.id)} title="Delete filter" style={{ padding: '7px 8px 7px 0', border: 'none', cursor: 'pointer', background: 'transparent', color: on ? '#0a1610' : '#7e9384', fontSize: 13 }}>×</button>
                )}
              </span>
            );
          })}
          {!matchesActive && (
            <button onClick={saveCurrent} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', borderRadius: 11, cursor: 'pointer',
              border: '1px dashed rgba(94,255,160,.45)', background: 'rgba(94,255,160,.06)', color: '#5effa0', fontFamily: 'Satoshi', fontWeight: 700, fontSize: 12.5 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><path d="M12 5v14M5 12h14"/></svg>Save filter
            </button>
          )}
        </div>
      </div>

      {/* editorial header */}
      <div style={{ padding: '14px 4px 22px' }}>
        <div style={{ fontSize: 11.5, letterSpacing: '.22em', textTransform: 'uppercase', color: '#7e9384', marginBottom: 12 }}>
          {filtered.length} top-shelf {filtered.length === 1 ? 'product' : 'products'} · {dealCount} on sale · within {maxDist} mi of {locObj.label} ({locObj.sub})
        </div>
        <h1 style={{ margin: 0, fontFamily: 'Clash Display', fontWeight: 600, fontSize: 'clamp(34px,4.6vw,58px)', lineHeight: .98, letterSpacing: '-.03em', maxWidth: 820 }}>
          A curated floor of <span style={{ fontStyle: 'italic', color: '#d4af37' }}>top-shelf</span> picks, ranked best to worst.
        </h1>
      </div>

      {/* spotlight search */}
      <div style={{ position: 'relative', marginBottom: 16 }}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#7e9384" strokeWidth="2"
          style={{ position: 'absolute', left: 16, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}>
          <circle cx="11" cy="11" r="7" /><path d="M21 21l-4-4" />
        </svg>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search product, brand, or dispensary…"
          style={{ width: '100%', boxSizing: 'border-box', padding: '14px 44px', borderRadius: 14, fontFamily: 'Satoshi', fontSize: 15,
            color: '#f3ede0', background: 'rgba(255,255,255,.04)', border: '1px solid ' + (q ? 'rgba(212,175,55,.45)' : 'rgba(255,255,255,.1)'),
            outline: 'none', transition: 'border-color .18s' }} />
        {q && (
          <button onClick={() => setQ('')} title="Clear" style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
            border: 'none', background: 'rgba(255,255,255,.08)', color: '#cbd8cc', width: 24, height: 24, borderRadius: 12, cursor: 'pointer', fontSize: 14, lineHeight: 1 }}>×</button>
        )}
      </div>

      {/* category tabs */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
        {window.TS_CATS.map(c => {
          const on = cat === c; const Ic = Icon(c);
          return (
            <button key={c} onClick={() => setCat(c)} style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '9px 15px', borderRadius: 13, cursor: 'pointer',
              fontFamily: 'Satoshi', fontWeight: 600, fontSize: 13.5, transition: 'all .18s',
              border: '1px solid ' + (on ? 'transparent' : 'rgba(255,255,255,.1)'),
              background: on ? 'linear-gradient(135deg,#e8c662,#b8902e)' : 'rgba(255,255,255,.03)',
              color: on ? '#0a1610' : '#cbd8cc' }}>
              <Ic width="16" height="16" style={{ opacity: on ? 1 : .8 }} />{c}
            </button>
          );
        })}
      </div>

      {/* filter / sort bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '12px 16px', marginBottom: 24,
        background: 'rgba(255,255,255,.025)', border: '1px solid rgba(255,255,255,.08)', borderRadius: 14 }}>
        <span style={{ fontSize: 12, color: '#8aa394', fontWeight: 600 }}>Show</span>
        <div style={{ display: 'flex', gap: 3, background: 'rgba(0,0,0,.3)', padding: 3, borderRadius: 10 }}>
          {[['all', 'All products'], ['deals', 'Deals only']].map(([k, l]) => {
            const sel = (k === 'deals') === saleOnly;
            return (
              <button key={k} onClick={() => setSaleOnly(k === 'deals')} style={{
                padding: '6px 12px', borderRadius: 8, border: 'none', cursor: 'pointer', fontSize: 12.5, fontWeight: 600, fontFamily: 'Satoshi',
                background: sel ? 'rgba(232,198,98,.18)' : 'transparent', color: sel ? '#f1dd9e' : '#9fb3a4' }}>{l}</button>
            );
          })}
        </div>
        {layout === 'cards' && <React.Fragment>
          <span style={{ fontSize: 12, color: '#8aa394', fontWeight: 600 }}>Sort</span>
          <div style={{ display: 'flex', gap: 3, background: 'rgba(0,0,0,.3)', padding: 3, borderRadius: 10 }}>
            {[['score', 'Best score'], ['price', 'Price'], ['off', '% off'], ['dist', 'Distance']].map(([k, l]) => (
              <button key={k} onClick={() => setSort(k)} style={{
                padding: '6px 12px', borderRadius: 8, border: 'none', cursor: 'pointer', fontSize: 12.5, fontWeight: 600, fontFamily: 'Satoshi',
                background: sort === k ? 'rgba(94,255,160,.16)' : 'transparent', color: sort === k ? '#5effa0' : '#9fb3a4' }}>{l}</button>
            ))}
          </div>
        </React.Fragment>}
        <span style={{ fontSize: 12, color: '#8aa394', fontWeight: 600, marginLeft: 6 }}>Layout</span>
        <div style={{ display: 'flex', gap: 3, background: 'rgba(0,0,0,.3)', padding: 3, borderRadius: 10 }}>
          {[['cards', 'Cards'], ['table', 'Table']].map(([k, l]) => {
            const sel = layout === k;
            return (
              <button key={k} onClick={() => setLayout(k)} style={{
                padding: '6px 12px', borderRadius: 8, border: 'none', cursor: 'pointer', fontSize: 12.5, fontWeight: 600, fontFamily: 'Satoshi',
                background: sel ? 'rgba(94,255,160,.16)' : 'transparent', color: sel ? '#5effa0' : '#9fb3a4' }}>{l}</button>
            );
          })}
        </div>
        {layout === 'cards' && <React.Fragment>
          <span style={{ fontSize: 12, color: '#8aa394', fontWeight: 600, marginLeft: 6 }}>Group</span>
          <div style={{ display: 'flex', gap: 3, background: 'rgba(0,0,0,.3)', padding: 3, borderRadius: 10 }}>
            {[['flat', 'Best deals'], ['shop', 'By shop']].map(([k, l]) => {
              const sel = (k === 'shop') === groupByShop;
              return (
                <button key={k} onClick={() => setGroupByShop(k === 'shop')} style={{
                  padding: '6px 12px', borderRadius: 8, border: 'none', cursor: 'pointer', fontSize: 12.5, fontWeight: 600, fontFamily: 'Satoshi',
                  background: sel ? 'rgba(232,198,98,.18)' : 'transparent', color: sel ? '#f1dd9e' : '#9fb3a4' }}>{l}</button>
              );
            })}
          </div>
        </React.Fragment>}
        <div style={{ flex: 1 }} />
        <button onClick={() => setInStock(v => !v)} style={{
          display: 'flex', alignItems: 'center', gap: 7, padding: '7px 13px', borderRadius: 10, cursor: 'pointer', fontSize: 12.5, fontWeight: 600, fontFamily: 'Satoshi',
          border: '1px solid ' + (inStock ? 'rgba(94,255,160,.4)' : 'rgba(255,255,255,.12)'), background: inStock ? 'rgba(94,255,160,.12)' : 'transparent', color: inStock ? '#5effa0' : '#cbd8cc' }}>
          <span style={{ width: 8, height: 8, borderRadius: 9, background: inStock ? '#5effa0' : '#5a6a5f' }} />In stock only
        </button>
        <button onClick={() => setShowFilters(v => !v)} style={{
          display: 'flex', alignItems: 'center', gap: 7, padding: '7px 13px', borderRadius: 10, cursor: 'pointer', fontSize: 12.5, fontWeight: 600, fontFamily: 'Satoshi',
          border: '1px solid rgba(255,255,255,.12)', background: showFilters ? 'rgba(255,255,255,.06)' : 'transparent', color: '#cbd8cc' }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 6h16M7 12h10M10 18h4"/></svg>Filters
        </button>
      </div>

      {showFilters && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))', gap: 22, padding: '18px 20px', marginBottom: 24, marginTop: -12,
          background: 'rgba(255,255,255,.025)', border: '1px solid rgba(255,255,255,.08)', borderRadius: 14 }}>
          <label style={{ display: 'block' }}>
            <div style={dbFLabel}><span>Max distance</span><span style={{ color: '#5effa0' }}>{maxDist} mi</span></div>
            <input type="range" min="1" max="25" step="0.5" value={maxDist} onChange={e => setMaxDist(+e.target.value)} style={dbRange} />
          </label>
          <label style={{ display: 'block' }}>
            <div style={dbFLabel}><span>Min % off</span><span style={{ color: '#5effa0' }}>{minOff}%</span></div>
            <input type="range" min="0" max="60" step="1" value={minOff} onChange={e => setMinOff(+e.target.value)} style={dbRange} />
          </label>
          <label style={{ display: 'block' }}>
            <div style={dbFLabel}><span>Min THC</span><span style={{ color: '#5effa0' }}>{minThc ? minThc + '%' : 'Any'}</span></div>
            <input type="range" min="0" max="40" step="1" value={minThc} onChange={e => setMinThc(+e.target.value)} style={dbRange} />
          </label>
          <label style={{ display: 'block' }}>
            <div style={dbFLabel}><span>Max $/unit</span><span style={{ color: '#5effa0' }}>{maxUnit ? '$' + maxUnit : 'Any'}</span></div>
            <input type="range" min="0" max="60" step="1" value={maxUnit} onChange={e => setMaxUnit(+e.target.value)} style={dbRange} />
          </label>
          <label style={{ display: 'block' }}>
            <div style={dbFLabel}><span>Max price</span><span style={{ color: '#5effa0' }}>{maxPrice ? '$' + maxPrice : 'Any'}</span></div>
            <input type="range" min="0" max="200" step="5" value={maxPrice} onChange={e => setMaxPrice(+e.target.value)} style={dbRange} />
          </label>
          <div>
            <div style={dbFLabel}><span>Strain</span></div>
            <div style={dbChipWrap}>{['Indica', 'Sativa', 'Hybrid'].map(s => <button key={s} onClick={() => toggleIn(strains, setStrains, s)} style={dbChip(strains.includes(s))}>{s}</button>)}</div>
          </div>
          <div>
            <div style={dbFLabel}><span>Brand tier</span></div>
            <div style={dbChipWrap}>{['S', 'A', 'B'].map(t => <button key={t} onClick={() => toggleIn(tiers, setTiers, t)} style={dbChip(tiers.includes(t))}>{t}</button>)}</div>
          </div>
          <div>
            <div style={dbFLabel}><span>Quick</span></div>
            <div style={dbChipWrap}>
              <button onClick={() => setFireOnly(v => !v)} style={dbChip(fireOnly)}>🔥 Fire only</button>
            </div>
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={dbFLabel}><span>Brand{brands.length ? ' · ' + brands.length : ''}</span>{brands.length > 0 && <button onClick={() => setBrands([])} style={dbClear}>clear</button>}</div>
            <div style={{ ...dbChipWrap, maxHeight: 104, overflowY: 'auto' }}>{brandOptions.map(b => <button key={b} onClick={() => toggleIn(brands, setBrands, b)} style={dbChip(brands.includes(b))}>{b}</button>)}</div>
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={dbFLabel}><span>Dispensary{shops.length ? ' · ' + shops.length : ''}</span>{shops.length > 0 && <button onClick={() => setShops([])} style={dbClear}>clear</button>}</div>
            <div style={{ ...dbChipWrap, maxHeight: 104, overflowY: 'auto' }}>{shopOptions.map(s => <button key={s} onClick={() => toggleIn(shops, setShops, s)} style={dbChip(shops.includes(s))}>{s}</button>)}</div>
          </div>
        </div>
      )}

      {filtered.length === 0 ? (
        <div style={{ padding: '80px 0', textAlign: 'center', color: '#7e9384' }}>No products match these filters. Loosen distance or % off.</div>
      ) : layout === 'table' ? (
        <DealTable rows={tableRows} onOpen={onOpen} onPing={onPing} pingedIds={pingedIds} loc={loc} tSort={tSort} onSort={onTableSort} />
      ) : groupByShop ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 30 }}>
          {shopGroups.map(g => (
            <div key={g.shop}>
              {/* shop header (nearest -> furthest) */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '0 2px 12px', borderBottom: '1px solid rgba(255,255,255,.07)', marginBottom: 16 }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#e8c662" strokeWidth="2"><path d="M12 21s-7-6.3-7-11a7 7 0 0114 0c0 4.7-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/></svg>
                <span style={{ fontFamily: 'Clash Display', fontWeight: 600, fontSize: 22, color: '#f3ede0', letterSpacing: '-.01em' }}>{g.shop}</span>
                <span style={{ fontSize: 12.5, color: '#5effa0', fontWeight: 700, background: 'rgba(94,255,160,.1)', border: '1px solid rgba(94,255,160,.3)', padding: '3px 9px', borderRadius: 20 }}>{g.dist} mi</span>
                <span style={{ fontSize: 12, color: '#8aa394' }}>{g.items.length} item{g.items.length === 1 ? '' : 's'}</span>
                <div style={{ flex: 1 }} />
                <a href={window.menuFor(g.shop)} target="_blank" rel="noopener" style={ghLink}>Menu ↗</a>
                <a href={window.mapsDirUrl(g.shop)} target="_blank" rel="noopener" style={{ ...ghLink, color: '#9fc2ff', borderColor: 'rgba(120,170,255,.3)', background: 'rgba(120,170,255,.08)' }}>Directions</a>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(248px,1fr))', gap: 20 }}>
                {g.items.map(d => <GlassCard key={d.id} d={d} onOpen={onOpen} onPing={onPing} pinged={pingedIds.has(d.id)} photo={photos['img-' + d.id]} loc={loc} />)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(300px,1fr) 2fr', gap: 24, alignItems: 'start' }} className="ts-dash-grid">
          {/* hero spotlight */}
          <div onClick={() => onOpen(hero)} style={{ position: 'relative', borderRadius: 24, padding: 0, minHeight: 430, cursor: 'pointer',
            background: 'linear-gradient(160deg, rgba(40,64,48,.62), rgba(10,22,15,.72))', border: '1px solid rgba(212,175,55,.32)',
            backdropFilter: 'blur(18px)', boxShadow: '0 50px 90px -36px rgba(0,0,0,.95), 0 1px 0 rgba(255,255,255,.12) inset', overflow: 'hidden' }}>
            <window.ProductShot d={hero} img={photos['img-' + hero.id]} height={236} radius={0} big>
              <div style={{ position: 'absolute', top: 18, left: 18, display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 10.5, fontWeight: 700, letterSpacing: '.1em', color: '#0a1610', background: 'linear-gradient(135deg,#e8c662,#b8902e)', padding: '6px 13px', borderRadius: 30, zIndex: 3, whiteSpace: 'nowrap' }}>
                {hero.off > 0 ? '#1 BEST DEAL TODAY' : '#1 TOP-SHELF PICK'}
              </div>
              <div style={{ position: 'absolute', top: 16, right: 16, zIndex: 3 }}><window.ScoreRing score={hero.score} size={56} /></div>
            </window.ProductShot>
            <div style={{ padding: '22px 28px 28px', position: 'relative' }}>
              <div style={{ color: '#d4af37', fontSize: 13.5, fontWeight: 600, letterSpacing: '.05em' }}>{hero.brand}</div>
              <div style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 38, lineHeight: 1, margin: '6px 0', letterSpacing: '-.02em' }}>{hero.product}</div>
              <div style={{ color: '#9fb3a4', fontSize: 13.5 }}>{hero.shop} · {window.getDist(hero, loc)} mi · {hero.size} · {hero.thc}% THC</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 13, marginTop: 16 }}>
                <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 52, color: '#fff' }}>${hero.sale}</span>
                {hero.off > 0 ? (
                  <React.Fragment>
                    <span style={{ color: '#6f8576', textDecoration: 'line-through', fontSize: 21 }}>${hero.orig}</span>
                    <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 28, color: '#5effa0', textShadow: '0 0 20px rgba(94,255,160,.5)' }}>−{hero.off}%</span>
                  </React.Fragment>
                ) : (
                  <span style={{ fontSize: 14, color: '#8aa394', fontWeight: 600, letterSpacing: '.04em' }}>at its regular menu price</span>
                )}
              </div>
            </div>
          </div>

          {/* floating depth grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(248px,1fr))', gap: 20 }}>
            {rest.map(d => <GlassCard key={d.id} d={d} onOpen={onOpen} onPing={onPing} pinged={pingedIds.has(d.id)} photo={photos['img-' + d.id]} loc={loc} />)}
          </div>
        </div>
      )}
    </div>
  );
}
const dbRange = { width: '100%', accentColor: '#5effa0', cursor: 'pointer' };
const ghLink = { display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5, fontWeight: 700, textDecoration: 'none',
  color: '#9af0c4', background: 'rgba(94,255,160,.1)', border: '1px solid rgba(94,255,160,.28)', borderRadius: 8, padding: '5px 11px' };
const dbFLabel = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12.5, color: '#cbd8cc', marginBottom: 8, fontWeight: 600 };
const dbChipWrap = { display: 'flex', flexWrap: 'wrap', gap: 6 };
const dbClear = { border: 'none', background: 'transparent', color: '#7e9384', fontSize: 11, fontFamily: 'Satoshi', cursor: 'pointer', fontWeight: 600 };
const dbChip = (on) => ({ padding: '5px 11px', borderRadius: 18, cursor: 'pointer', fontSize: 12, fontFamily: 'Satoshi', fontWeight: 600,
  border: '1px solid ' + (on ? 'transparent' : 'rgba(255,255,255,.14)'),
  background: on ? 'linear-gradient(135deg,#e8c662,#b8902e)' : 'rgba(255,255,255,.04)', color: on ? '#0a1610' : '#cbd8cc' });
window.Dashboard = Dashboard;
