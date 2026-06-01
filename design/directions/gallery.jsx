// Direction C — "Gallery Depth" : architectural layered depth. Floating cards, long shadows, glass refraction.
const { useState: galUseState } = React;

function GalCard({ d, z = 0, accent }) {
  const [hov, setHov] = galUseState(false);
  const lift = 6 + z * 4;
  return (
    <div onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)} style={{
      position: 'relative', borderRadius: 20, padding: 22, cursor: 'pointer',
      background: 'linear-gradient(160deg, rgba(34,56,42,.55), rgba(12,24,17,.66))',
      backdropFilter: 'blur(14px) saturate(140%)', WebkitBackdropFilter: 'blur(14px) saturate(140%)',
      border: '1px solid rgba(255,255,255,.1)',
      boxShadow: hov
        ? `0 ${lift+34}px ${lift+60}px -22px rgba(0,0,0,.9), 0 0 0 1px rgba(212,175,55,.35) inset, 0 1px 0 rgba(255,255,255,.14) inset`
        : `0 ${lift+18}px ${lift+38}px -24px rgba(0,0,0,.85), 0 1px 0 rgba(255,255,255,.08) inset`,
      transform: hov ? 'translateY(-10px) scale(1.015)' : `translateY(${-z*6}px)`,
      transition: 'all .3s cubic-bezier(.2,.8,.2,1)', display: 'flex', flexDirection: 'column', gap: 14,
    }}>
      {/* refraction highlight */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '45%', borderRadius: '20px 20px 0 0',
        background: 'linear-gradient(180deg, rgba(255,255,255,.07), transparent)', pointerEvents: 'none' }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '.14em', textTransform: 'uppercase', color: '#9fb3a4' }}>{d.cat}</span>
        <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 18, color: accent, textShadow: `0 0 16px ${accent}66` }}>−{d.off}%</span>
      </div>
      <div>
        <div style={{ color: '#d4af37', fontSize: 12, fontWeight: 600, letterSpacing: '.06em' }}>{d.brand}</div>
        <div style={{ fontFamily: 'Clash Display', fontWeight: 600, color: '#f3ede0', fontSize: 23, lineHeight: 1.02, marginTop: 3, letterSpacing: '-.01em' }}>{d.product}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 34, color: '#fff' }}>${d.sale}</span>
        <span style={{ color: '#6f8576', textDecoration: 'line-through', fontSize: 15 }}>${d.orig}</span>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: '#bcd3c4', background: 'rgba(255,255,255,.06)', padding: '3px 9px', borderRadius: 20, border: '1px solid rgba(255,255,255,.1)' }}>${d.unit.toFixed(1)}{d.unitLabel}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 12, borderTop: '1px solid rgba(255,255,255,.08)', fontSize: 12, color: '#8aa394' }}>
        <span>{d.shop}</span>
        <span>{d.dist} mi · {d.seen}</span>
      </div>
    </div>
  );
}

function GalleryDashboard() {
  const deals = window.TS_DEALS;
  const hero = [...deals].sort((a,b)=>b.score-a.score)[0];
  const rest = deals.filter(d => d.id !== hero.id).slice(0, 6);
  return (
    <div style={{ width: '100%', minHeight: '100%', color: '#f3ede0', fontFamily: 'Satoshi, sans-serif', paddingBottom: 50,
      background: 'radial-gradient(130% 90% at 15% -10%, #1a3a26 0%, #0a160f 45%, #060d09 100%)' }}>
      {/* thin top bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 40px' }}>
        <span style={{ fontFamily: 'Clash Display', fontWeight: 600, fontSize: 19, letterSpacing: '.02em' }}>TopShelf<span style={{ color: '#d4af37' }}>.</span></span>
        <div style={{ display: 'flex', gap: 26, alignItems: 'center', fontSize: 13, color: '#9fb3a4' }}>
          <span>Browse</span><span>Filters</span><span>Memory</span>
          <span style={{ color: '#d4af37', fontWeight: 600 }}>Saved $1,284 ↑</span>
        </div>
      </div>

      {/* big editorial header */}
      <div style={{ padding: '40px 40px 30px', maxWidth: 760 }}>
        <div style={{ fontSize: 12, letterSpacing: '.22em', textTransform: 'uppercase', color: '#7e9384', marginBottom: 14 }}>19 qualifying deals · within 7 mi</div>
        <h1 style={{ margin: 0, fontFamily: 'Clash Display', fontWeight: 600, fontSize: 60, lineHeight: .98, letterSpacing: '-.03em' }}>
          A curated floor of <span style={{ fontStyle: 'italic', color: '#d4af37' }}>top-shelf</span> deals, ranked.
        </h1>
      </div>

      {/* layered composition: hero spotlight + floating depth grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1.6fr', gap: 26, padding: '10px 40px 0', alignItems: 'start' }}>
        {/* hero spotlight panel */}
        <div style={{ position: 'relative', borderRadius: 26, padding: 30, minHeight: 440,
          background: 'linear-gradient(160deg, rgba(40,64,48,.6), rgba(10,22,15,.7))',
          border: '1px solid rgba(212,175,55,.3)', backdropFilter: 'blur(18px)',
          boxShadow: '0 50px 90px -36px rgba(0,0,0,.95), 0 1px 0 rgba(255,255,255,.12) inset' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 11, fontWeight: 700, letterSpacing: '.1em',
            color: '#0a1610', background: 'linear-gradient(135deg,#e8c662,#b8902e)', padding: '5px 12px', borderRadius: 30 }}>
            #1 BEST DEAL · SCORE {hero.score}
          </div>
          <div style={{ marginTop: 220 }}>
            <div style={{ color: '#d4af37', fontSize: 14, fontWeight: 600, letterSpacing: '.06em' }}>{hero.brand}</div>
            <div style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 42, lineHeight: 1, margin: '6px 0', letterSpacing: '-.02em' }}>{hero.product}</div>
            <div style={{ color: '#9fb3a4', fontSize: 14 }}>{hero.shop} · {hero.dist} mi · {hero.size}</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginTop: 18 }}>
              <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 54, color: '#fff' }}>${hero.sale}</span>
              <span style={{ color: '#6f8576', textDecoration: 'line-through', fontSize: 22 }}>${hero.orig}</span>
              <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 30, color: '#5effa0', textShadow: '0 0 20px rgba(94,255,160,.5)' }}>−{hero.off}%</span>
            </div>
          </div>
          {/* floating monogram */}
          <div style={{ position: 'absolute', top: 70, right: 30, fontFamily: 'Clash Display', fontWeight: 700, fontSize: 150, color: 'rgba(212,175,55,.1)', letterSpacing: '-.04em', lineHeight: 1 }}>
            {hero.brand.split(' ').map(w=>w[0]).join('').slice(0,2)}
          </div>
        </div>

        {/* floating depth grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 22 }}>
          {rest.map((d, i) => (
            <GalCard key={d.id} d={d} z={[2,1,1,0,0,1][i] || 0} accent={i % 2 ? '#d4af37' : '#5effa0'} />
          ))}
        </div>
      </div>
    </div>
  );
}
window.GalleryDashboard = GalleryDashboard;
