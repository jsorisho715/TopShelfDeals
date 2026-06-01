// Deal detail modal — big product image (fillable), strain info, effects, score breakdown, price history.
const { useEffect: dtUseEffect } = React;

function FactorBar({ f, max }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '116px 1fr 34px', alignItems: 'center', gap: 12 }}>
      <span style={{ fontSize: 12.5, color: '#cbd8cc' }}>{f.key}</span>
      <div style={{ position: 'relative', height: 8, borderRadius: 6, background: 'rgba(255,255,255,.07)', overflow: 'hidden' }} title={f.hint}>
        <div style={{ position: 'absolute', inset: 0, width: `${(f.v / max) * 100}%`, borderRadius: 6,
          background: 'linear-gradient(90deg,#1f8a5b,#5effa0)', boxShadow: '0 0 10px rgba(94,255,160,.45)' }} />
      </div>
      <span style={{ fontSize: 12.5, color: '#5effa0', fontWeight: 700, textAlign: 'right', fontFamily: 'Clash Display' }}>+{f.v}</span>
    </div>
  );
}

function DealDetail({ d, onClose, onPing, pinged, loc }) {
  dtUseEffect(() => {
    const k = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', k);
    document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', k); document.body.style.overflow = ''; };
  }, [onClose]);
  if (!d) return null;
  const t = window.strainTone(d.type);
  const maxF = Math.max(...d.factors.map(f => f.v));
  const accent = d.score >= 93 ? '#5effa0' : '#e8c662';
  const platform = { 'Sol Flower': 'Sol Flower menu', 'The Mint': 'Dutchie', 'Cookies on Camelback': 'Cookies.co', 'TruMed': 'TruMed menu', 'Sunday Goods': 'Dutchie', 'Nirvana Center': 'Leafly', 'Story Cannabis': 'Dutchie', 'Local Joint': 'Weedmaps', 'Curaleaf': 'Curaleaf menu' }[d.shop] || 'menu';

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 20, background: 'rgba(4,8,6,.72)', backdropFilter: 'blur(10px)', opacity: 1 }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 'min(940px, 96vw)', maxHeight: '92vh', overflowY: 'auto', borderRadius: 24,
        background: 'linear-gradient(165deg, rgba(26,46,33,.96), rgba(9,18,13,.98))', border: '1px solid rgba(212,175,55,.3)',
        boxShadow: '0 60px 120px -30px rgba(0,0,0,.9)', animation: 'tsRise .28s cubic-bezier(.2,.8,.2,1)' }}>
        <div className="ts-detail-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr' }}>
          {/* left: product image */}
          <div style={{ position: 'relative', minHeight: 380 }}>
            <window.ProductShot d={d} height={'100%'} big radius={0} />
            <image-slot id={'img-' + d.id} class="ts-slot" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
              shape="rect" placeholder={`Drop a real ${d.brand} photo`}></image-slot>
            <div style={{ position: 'absolute', top: 16, left: 16, display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 10.5, fontWeight: 700, letterSpacing: '.1em', color: '#0a1610', background: 'linear-gradient(135deg,#e8c662,#b8902e)', padding: '6px 13px', borderRadius: 30, zIndex: 4, pointerEvents: 'none', whiteSpace: 'nowrap' }}>
              SCORE {d.score} · {d.tier}-TIER
            </div>
          </div>

          {/* right: info */}
          <div style={{ padding: '26px 28px 28px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ color: '#d4af37', fontSize: 13, fontWeight: 600, letterSpacing: '.06em' }}>{d.brand}</div>
                <h2 style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 34, lineHeight: 1, margin: '4px 0 0', letterSpacing: '-.02em' }}>{d.product}</h2>
              </div>
              <button onClick={onClose} style={{ flexShrink: 0, width: 34, height: 34, borderRadius: 10, border: '1px solid rgba(255,255,255,.14)', background: 'rgba(255,255,255,.05)', color: '#cbd8cc', cursor: 'pointer', fontSize: 18, lineHeight: 1 }}>×</button>
            </div>

            {/* tags */}
            <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 14 }}>
              <span style={{ fontSize: 11.5, fontWeight: 700, letterSpacing: '.05em', color: t.text, background: t.tag, border: `1px solid ${t.tagB}`, padding: '5px 11px', borderRadius: 20 }}>{d.type}</span>
              <span style={dtChip}>{d.thc}{d.unitLabel === '/10mg' ? 'mg' : '% THC'}</span>
              <span style={dtChip}>{d.size}</span>
              <span style={dtChip}>{d.shop} · {window.getDist(d, loc)} mi</span>
              {d.stock ? <span style={{ ...dtChip, color: '#5effa0', borderColor: 'rgba(94,255,160,.35)' }}>● In stock</span>
                       : <span style={{ ...dtChip, color: '#ff8a6a', borderColor: 'rgba(255,138,106,.35)' }}>● Sold out</span>}
            </div>

            {/* price */}
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginTop: 18 }}>
              <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 44, color: '#fff' }}>${d.sale}</span>
              {d.off > 0 ? (
                <React.Fragment>
                  <span style={{ color: '#6f8576', textDecoration: 'line-through', fontSize: 18 }}>${d.orig}</span>
                  <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 24, color: accent, textShadow: `0 0 16px ${accent}66` }}>−{d.off}%</span>
                </React.Fragment>
              ) : (
                <span style={{ fontSize: 13, color: '#8aa394', fontWeight: 600, letterSpacing: '.04em' }}>regular menu price</span>
              )}
              <span style={{ marginLeft: 'auto', fontSize: 13, color: '#bcd3c4', background: 'rgba(255,255,255,.06)', padding: '5px 11px', borderRadius: 20, border: '1px solid rgba(255,255,255,.1)' }}>${d.unit.toFixed(1)}{d.unitLabel}</span>
            </div>

            {/* description */}
            <p style={{ color: '#c4d2c7', fontSize: 14, lineHeight: 1.55, margin: '16px 0 0', textWrap: 'pretty' }}>{d.desc}</p>

            {/* detailed spec grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 18px', marginTop: 14, padding: '14px 16px', borderRadius: 14, background: 'rgba(255,255,255,.03)', border: '1px solid rgba(255,255,255,.08)' }}>
              {[['Strain type', d.type], ['THC', d.unitLabel === '/10mg' ? d.thc + 'mg total' : d.thc + '%'], ['CBD', (d.cbd || 0) + '%'], ['Size', d.size],
                ['Dispensary', d.shop], ['Distance', window.getDist(d, loc) + ' mi away']].map(([k, v]) => (
                <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ fontSize: 10.5, color: '#7e9384', letterSpacing: '.08em', textTransform: 'uppercase' }}>{k}</span>
                  <span style={{ fontSize: 13.5, color: '#e9f1ea', fontWeight: 600 }}>{v}</span>
                </div>
              ))}
              <div style={{ gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', gap: 2 }}>
                <span style={{ fontSize: 10.5, color: '#7e9384', letterSpacing: '.08em', textTransform: 'uppercase' }}>Lineage</span>
                <span style={{ fontSize: 13.5, color: '#e9f1ea', fontWeight: 600 }}>{d.lineage}</span>
              </div>
            </div>

            {/* effects */}
            <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 14 }}>
              {d.effects.map(e => <span key={e} style={{ fontSize: 12, color: '#dfe9e0', background: 'rgba(255,255,255,.05)', border: '1px solid rgba(255,255,255,.1)', padding: '5px 11px', borderRadius: 20 }}>{e}</span>)}
            </div>

            {/* score breakdown */}
            <div style={{ marginTop: 22, padding: '16px 16px 18px', borderRadius: 14, background: 'rgba(255,255,255,.03)', border: '1px solid rgba(255,255,255,.08)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: '#9fb3a4' }}>Why it ranks {d.score}</span>
                <window.ScoreRing score={d.score} size={42} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                {d.factors.map(f => <FactorBar key={f.key} f={f} max={maxF} />)}
              </div>
            </div>

            {/* price memory */}
            <div style={{ marginTop: 16, padding: '14px 16px', borderRadius: 14, background: 'rgba(255,255,255,.03)', border: '1px solid rgba(255,255,255,.08)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: '#9fb3a4' }}>Price memory · 14 days</span>
                {d.fire
                  ? <span style={{ fontSize: 11.5, color: '#ff9b6a', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 5 }}>🔥 Fire deal</span>
                  : d.isTrap
                    ? <span style={{ fontSize: 11.5, color: '#f0b44a', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 5 }}>⚠ Markup trap</span>
                    : d.off > 0
                      ? <span style={{ fontSize: 11.5, color: '#5effa0', display: 'flex', alignItems: 'center', gap: 5 }}>
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><path d="M20 6L9 17l-5-5"/></svg>Validated</span>
                      : <span style={{ fontSize: 11.5, color: '#9fb3a4', display: 'flex', alignItems: 'center', gap: 5 }}>● Menu price</span>}
              </div>
              <div style={{ marginTop: 10 }}><window.Sparkline data={d.hist} w={360} h={58} sale={d.sale} avg={d.priorAvg} /></div>
              <div style={{ display: 'flex', gap: 16, marginTop: 12, flexWrap: 'wrap' }}>
                <div><span style={dtMemK}>Lowest tracked</span><span style={{ ...dtMemV, color: d.isLowest ? '#5effa0' : '#e9f1ea' }}>${Math.min(d.priorMin, d.sale)}{d.isLowest ? ' · today' : ''}</span></div>
                <div><span style={dtMemK}>14-day avg</span><span style={dtMemV}>${Math.round(d.priorAvg)}</span></div>
                <div><span style={dtMemK}>vs its avg</span><span style={{ ...dtMemV, color: '#5effa0' }}>−{d.pctBelowAvg}%</span></div>
              </div>
              <div style={{ fontSize: 12, color: d.fire ? '#ffb892' : d.isTrap ? '#f0c777' : '#8aa394', marginTop: 10, textWrap: 'pretty' }}>{d.fireReason}.</div>
            </div>

            {/* recurring */}
            {d.recurring && (
              <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', borderRadius: 12, background: 'rgba(212,175,55,.08)', border: '1px solid rgba(212,175,55,.28)' }}>
                <span style={{ fontSize: 18 }}>↻</span>
                <div style={{ fontSize: 13, color: '#e8d9a8' }}>Recurs most <b style={{ color: '#f3e4b0' }}>{d.dow}s</b> — we'll remind you the evening before.</div>
              </div>
            )}

            {/* actions */}
            <div style={{ display: 'flex', gap: 10, marginTop: 20, flexWrap: 'wrap' }}>
              <a href={window.specialFor(d)} target="_blank" rel="noopener" style={{ flex: 1, minWidth: 150, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, textDecoration: 'none', padding: '13px 18px', borderRadius: 12, fontWeight: 700, fontSize: 14, fontFamily: 'Satoshi', color: '#0a1610', background: 'linear-gradient(135deg,#e8c662,#b8902e)', boxShadow: '0 10px 26px -10px rgba(212,175,55,.6)' }}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M7 17L17 7M17 7H8M17 7v9"/></svg>
                View the special on {window.platformFor(d.shop)}
              </a>
              <a href={window.mapsDirUrl(d.shop)} target="_blank" rel="noopener" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '13px 18px', borderRadius: 12, fontWeight: 700, fontSize: 14, fontFamily: 'Satoshi', textDecoration: 'none',
                border: '1px solid rgba(120,170,255,.4)', background: 'rgba(120,170,255,.1)', color: '#bcd3ff' }}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 11l19-9-9 19-2-8-8-2z"/></svg>
                Directions
              </a>
              <button onClick={() => onPing(d)} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '13px 18px', borderRadius: 12, fontWeight: 700, fontSize: 14, fontFamily: 'Satoshi', cursor: 'pointer',
                border: '1px solid ' + (pinged ? 'rgba(94,255,160,.5)' : 'rgba(255,255,255,.16)'), background: pinged ? 'rgba(94,255,160,.14)' : 'rgba(255,255,255,.05)', color: pinged ? '#5effa0' : '#e9f1ea' }}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
                {pinged ? 'Sent to Telegram' : 'Ping to Telegram'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
const dtChip = { fontSize: 11.5, color: '#cbd8cc', background: 'rgba(255,255,255,.05)', border: '1px solid rgba(255,255,255,.12)', padding: '5px 11px', borderRadius: 20 };
const dtMemK = { display: 'block', fontSize: 10, color: '#7e9384', letterSpacing: '.06em', textTransform: 'uppercase' };
const dtMemV = { display: 'block', fontFamily: 'Clash Display, sans-serif', fontWeight: 700, fontSize: 17, color: '#e9f1ea', marginTop: 2 };
window.DealDetail = DealDetail;
