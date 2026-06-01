// Direction A — "The Vault" : refined editorial luxe. Gold foil, glass, generous negative space.
const { useRef: vaultUseRef, useState: vaultUseState } = React;

function VaultTilt({ children, max = 8, style, className }) {
  const ref = vaultUseRef(null);
  const onMove = (e) => {
    const el = ref.current; if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    el.style.transform = `perspective(900px) rotateY(${px * max}deg) rotateX(${-py * max}deg) translateZ(14px)`;
    const gl = el.querySelector('[data-glare]');
    if (gl) { gl.style.opacity = .35; gl.style.background = `radial-gradient(420px circle at ${(px+0.5)*100}% ${(py+0.5)*100}%, rgba(255,245,210,.55), transparent 60%)`; }
  };
  const onLeave = () => {
    const el = ref.current; if (!el) return;
    el.style.transform = 'perspective(900px) rotateY(0) rotateX(0) translateZ(0)';
    const gl = el.querySelector('[data-glare]'); if (gl) gl.style.opacity = 0;
  };
  return (
    <div ref={ref} onMouseMove={onMove} onMouseLeave={onLeave} className={className}
      style={{ transition: 'transform .25s cubic-bezier(.2,.8,.2,1)', transformStyle: 'preserve-3d', ...style }}>
      {children}
    </div>
  );
}

function VaultCard({ d, big }) {
  return (
    <VaultTilt max={big ? 6 : 9} style={{ height: '100%' }}>
      <div style={{
        position: 'relative', height: '100%', borderRadius: 18, overflow: 'hidden',
        background: 'linear-gradient(155deg, rgba(28,52,38,.72), rgba(10,22,16,.82))',
        border: '1px solid rgba(212,175,55,.28)',
        boxShadow: '0 1px 0 rgba(255,245,210,.08) inset, 0 30px 60px -28px rgba(0,0,0,.85)',
        display: 'flex', flexDirection: 'column',
      }}>
        <div data-glare style={{ position: 'absolute', inset: 0, opacity: 0, transition: 'opacity .25s', pointerEvents: 'none', zIndex: 4 }} />
        {/* product placeholder */}
        <div style={{
          position: 'relative', height: big ? 240 : 132, flexShrink: 0,
          background: `radial-gradient(120% 90% at 30% 10%, rgba(61,220,132,.14), transparent 55%), linear-gradient(135deg, #11271b, #0a1610)`,
          borderBottom: '1px solid rgba(212,175,55,.18)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{ fontFamily: 'Clash Display, sans-serif', fontWeight: 700, fontSize: big ? 84 : 46, color: 'rgba(212,175,55,.16)', letterSpacing: '-.03em' }}>
            {d.brand.split(' ').map(w => w[0]).join('').slice(0,2)}
          </div>
          <div style={{ position: 'absolute', top: 12, left: 12, display: 'flex', gap: 6 }}>
            <span style={vTierStyle}>{d.tier}-TIER</span>
            {d.hot && <span style={vHotStyle}>HOT</span>}
          </div>
          <div style={{ position: 'absolute', top: 12, right: 12, fontFamily: 'Clash Display', fontWeight: 700,
            fontSize: big ? 30 : 22, color: '#5effa0', textShadow: '0 0 18px rgba(61,220,132,.5)' }}>
            −{d.off}%
          </div>
          {!d.stock && <div style={vStaleStyle}>SOLD OUT</div>}
        </div>
        {/* body */}
        <div style={{ padding: big ? '20px 22px' : '14px 16px', display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
            <span style={{ color: '#e8c662', fontWeight: 700, fontSize: big ? 15 : 12, letterSpacing: '.08em', textTransform: 'uppercase' }}>{d.brand}</span>
            <span style={{ color: '#7e9384', fontSize: 11 }}>{d.size}</span>
          </div>
          <div style={{ fontFamily: 'Clash Display, sans-serif', fontWeight: 600, color: '#f3ede0', fontSize: big ? 30 : 18, lineHeight: 1.05, letterSpacing: '-.01em' }}>{d.product}</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 'auto' }}>
            <span style={{ fontFamily: 'Clash Display', fontWeight: 700, color: '#d4af37', fontSize: big ? 40 : 26 }}>${d.sale}</span>
            <span style={{ color: '#6f8576', textDecoration: 'line-through', fontSize: big ? 18 : 14 }}>${d.orig}</span>
            <span style={vUnitStyle}>${d.unit.toFixed(1)}{d.unitLabel}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 10, borderTop: '1px solid rgba(212,175,55,.14)', fontSize: 11.5, color: '#8aa394' }}>
            <span>{d.shop} · {d.dist} mi</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 6, height: 6, borderRadius: 9, background: '#3ddc84', boxShadow: '0 0 8px #3ddc84' }} />{d.seen}
            </span>
          </div>
        </div>
      </div>
    </VaultTilt>
  );
}

const vTierStyle = { fontSize: 9, fontWeight: 700, letterSpacing: '.12em', color: '#0a1610', background: 'linear-gradient(135deg,#e8c662,#b8902e)', padding: '3px 7px', borderRadius: 5 };
const vHotStyle = { fontSize: 9, fontWeight: 700, letterSpacing: '.12em', color: '#fff', background: 'linear-gradient(135deg,#ff6a3d,#d62f2f)', padding: '3px 7px', borderRadius: 5, boxShadow: '0 0 14px rgba(255,80,40,.5)' };
const vUnitStyle = { fontSize: 11, color: '#bcd3c4', background: 'rgba(61,220,132,.1)', border: '1px solid rgba(61,220,132,.25)', padding: '2px 8px', borderRadius: 20 };
const vStaleStyle = { position: 'absolute', bottom: 12, left: 12, fontSize: 9, fontWeight: 700, letterSpacing: '.12em', color: '#f3ede0', background: 'rgba(0,0,0,.55)', border: '1px solid rgba(255,255,255,.2)', padding: '3px 7px', borderRadius: 5 };

function VaultDashboard() {
  const deals = window.TS_DEALS;
  const hero = deals[0];
  const grid = deals.slice(1, 7);
  const [cat, setCat] = vaultUseState('All');
  return (
    <div style={{
      width: '100%', minHeight: '100%', background: 'radial-gradient(120% 80% at 80% -10%, #15301f 0%, #07100b 55%)',
      color: '#f3ede0', fontFamily: 'Satoshi, sans-serif', padding: '0 0 40px',
    }}>
      {/* topbar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '22px 36px', borderBottom: '1px solid rgba(212,175,55,.16)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 34, height: 34, borderRadius: 9, background: 'linear-gradient(135deg,#e8c662,#b8902e)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#0a1610', fontFamily: 'Clash Display', fontWeight: 700, fontSize: 20, boxShadow: '0 0 22px rgba(212,175,55,.4)' }}>T</div>
          <div style={{ fontFamily: 'Clash Display', fontWeight: 600, fontSize: 20, letterSpacing: '-.01em' }}>TopShelf</div>
          <span style={{ color: '#6f8576', fontSize: 12, marginLeft: 4 }}>Scottsdale · 7 mi</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, color: '#8aa394', letterSpacing: '.1em', textTransform: 'uppercase' }}>Saved this month</div>
            <div style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 24, color: '#d4af37' }}>$1,284</div>
          </div>
          <div style={{ width: 38, height: 38, borderRadius: 11, background: 'rgba(255,255,255,.05)', border: '1px solid rgba(212,175,55,.25)' }} />
        </div>
      </div>

      {/* hero header */}
      <div style={{ padding: '34px 36px 18px' }}>
        <div style={{ fontSize: 12, color: '#8aa394', letterSpacing: '.18em', textTransform: 'uppercase', marginBottom: 6 }}>Today's best on top-shelf</div>
        <h1 style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 56, lineHeight: .95, letterSpacing: '-.03em', margin: 0,
          background: 'linear-gradient(180deg,#fff 20%,#cbb277 120%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
          The vault is<br/>stacked tonight.
        </h1>
      </div>

      {/* category filter */}
      <div style={{ display: 'flex', gap: 8, padding: '6px 36px 26px', flexWrap: 'wrap' }}>
        {window.TS_CATS.map(c => (
          <button key={c} onClick={() => setCat(c)} style={{
            padding: '8px 16px', borderRadius: 22, fontFamily: 'Satoshi', fontWeight: 500, fontSize: 13, cursor: 'pointer',
            border: '1px solid ' + (cat === c ? 'transparent' : 'rgba(212,175,55,.28)'),
            background: cat === c ? 'linear-gradient(135deg,#e8c662,#b8902e)' : 'transparent',
            color: cat === c ? '#0a1610' : '#cbd8cc',
          }}>{c}</button>
        ))}
      </div>

      {/* hero + grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.15fr 2fr', gap: 18, padding: '0 36px' }}>
        <div style={{ height: 520 }}><VaultCard d={hero} big /></div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gridAutoRows: '252px', gap: 18 }}>
          {grid.map(d => <VaultCard key={d.id} d={d} />)}
        </div>
      </div>
    </div>
  );
}
window.VaultDashboard = VaultDashboard;
