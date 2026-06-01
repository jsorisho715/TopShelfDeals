// Direction B — "Arcade Score" : gamified energy. Extruded 3D type, neon mint, deal-score rings.
const { useState: arcUseState, useEffect: arcUseEffect, useRef: arcUseRef } = React;

function ScoreRing({ score, size = 54 }) {
  const r = (size - 8) / 2, c = 2 * Math.PI * r;
  const col = score >= 93 ? '#5effa0' : score >= 85 ? '#d4af37' : '#e08a3d';
  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="rgba(255,255,255,.1)" strokeWidth="4" />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={col} strokeWidth="4" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - score/100)} style={{ filter: `drop-shadow(0 0 6px ${col})`, transition: 'stroke-dashoffset 1s' }} />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column' }}>
        <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: size > 50 ? 18 : 14, color: col, lineHeight: 1 }}>{score}</span>
      </div>
    </div>
  );
}

function ArcCard({ d }) {
  const [hov, setHov] = arcUseState(false);
  return (
    <div onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)} style={{
      position: 'relative', borderRadius: 16, padding: 16, cursor: 'pointer',
      background: 'linear-gradient(165deg, #161a24, #0c0e15)',
      border: '1px solid ' + (hov ? 'rgba(94,255,160,.5)' : 'rgba(255,255,255,.08)'),
      boxShadow: hov ? '0 24px 50px -20px rgba(94,255,160,.3), 0 0 0 1px rgba(94,255,160,.2)' : '0 16px 34px -22px rgba(0,0,0,.9)',
      transform: hov ? 'translateY(-6px)' : 'none', transition: 'all .22s cubic-bezier(.2,.8,.2,1)',
      display: 'flex', flexDirection: 'column', gap: 12,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {d.hot && <span style={arcFireStyle}>🔥 ON FIRE</span>}
          {d.recurring && <span style={arcRecurStyle}>↻ {d.dow}s</span>}
        </div>
        <ScoreRing score={d.score} />
      </div>
      <div>
        <div style={{ color: '#5effa0', fontWeight: 700, fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase' }}>{d.brand}</div>
        <div style={{ fontFamily: 'Clash Display', fontWeight: 600, color: '#fff', fontSize: 19, lineHeight: 1.05, marginTop: 2 }}>{d.product}</div>
        <div style={{ color: '#7d8595', fontSize: 12, marginTop: 3 }}>{d.shop} · {d.dist} mi · {d.size}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginTop: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontFamily: 'Clash Display', fontWeight: 700, color: '#fff', fontSize: 30 }}>${d.sale}</span>
          <span style={{ color: '#5d6575', textDecoration: 'line-through', fontSize: 14 }}>${d.orig}</span>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 24, color: '#5effa0', textShadow: '0 0 16px rgba(94,255,160,.6)' }}>−{d.off}%</div>
          <div style={{ fontSize: 11, color: '#9aa3b2' }}>${d.unit.toFixed(1)}{d.unitLabel}</div>
        </div>
      </div>
    </div>
  );
}
const arcFireStyle = { fontSize: 10, fontWeight: 700, letterSpacing: '.06em', color: '#fff', background: 'linear-gradient(135deg,#ff7a3d,#e0322f)', padding: '4px 9px', borderRadius: 20 };
const arcRecurStyle = { fontSize: 10, fontWeight: 700, letterSpacing: '.06em', color: '#0a1610', background: 'linear-gradient(135deg,#e8c662,#b8902e)', padding: '4px 9px', borderRadius: 20 };

function useCountUp(target, dur = 1400) {
  const [v, setV] = arcUseState(0);
  arcUseEffect(() => {
    let raf, start;
    const tick = (t) => { if (!start) start = t; const p = Math.min((t - start) / dur, 1);
      setV(Math.floor((1 - Math.pow(1 - p, 3)) * target)); if (p < 1) raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick); return () => cancelAnimationFrame(raf);
  }, [target]);
  return v;
}

function ArcadeDashboard() {
  const deals = window.TS_DEALS;
  const saved = useCountUp(1284);
  const top = [...deals].sort((a,b)=>b.score-a.score).slice(0, 8);
  return (
    <div style={{ width: '100%', minHeight: '100%', background: '#08090e', color: '#fff', fontFamily: 'Satoshi, sans-serif',
      backgroundImage: 'radial-gradient(60% 50% at 50% -5%, rgba(94,255,160,.1), transparent), radial-gradient(40% 40% at 90% 0%, rgba(212,175,55,.08), transparent)', paddingBottom: 40 }}>
      {/* topbar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '18px 32px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 32, height: 32, borderRadius: 9, background: 'linear-gradient(135deg,#5effa0,#1f8a5b)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#04130b', fontFamily: 'Clash Display', fontWeight: 700, fontSize: 19 }}>T</div>
          <span style={{ fontFamily: 'Clash Display', fontWeight: 600, fontSize: 18 }}>TopShelf</span>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: '#7d8595' }}>🔥 4-week streak</span>
          <div style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(255,255,255,.06)' }} />
        </div>
      </div>

      {/* hero extruded type + counter */}
      <div style={{ padding: '20px 32px 8px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 20 }}>
        <h1 style={{ margin: 0, fontFamily: 'Clash Display', fontWeight: 700, fontSize: 92, lineHeight: .82, letterSpacing: '-.04em',
          color: '#fff', textShadow: '0 1px 0 #2a8f5c, 0 2px 0 #25814f, 0 3px 0 #1f7244, 0 4px 0 #1a6239, 0 5px 0 #155330, 0 6px 0 #114627, 0 14px 30px rgba(0,0,0,.6)' }}>
          SAVE<br/><span style={{ color: '#5effa0', textShadow: '0 1px 0 #b8902e,0 2px 0 #a37f28,0 3px 0 #8e6e22,0 4px 0 #795d1c,0 16px 30px rgba(94,255,160,.3)' }}>BIG.</span>
        </h1>
        <div style={{ background: 'linear-gradient(165deg,#11151d,#0a0c12)', border: '1px solid rgba(94,255,160,.25)', borderRadius: 18, padding: '18px 26px', boxShadow: '0 0 40px -10px rgba(94,255,160,.25)' }}>
          <div style={{ fontSize: 11, color: '#9aa3b2', letterSpacing: '.14em', textTransform: 'uppercase' }}>Money saved this month</div>
          <div style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 52, color: '#5effa0', textShadow: '0 0 30px rgba(94,255,160,.5)', lineHeight: 1 }}>${saved.toLocaleString()}</div>
          <div style={{ fontSize: 12, color: '#7d8595', marginTop: 4 }}>across 23 qualifying deals</div>
        </div>
      </div>

      {/* filter chips */}
      <div style={{ display: 'flex', gap: 8, padding: '20px 32px 20px', flexWrap: 'wrap' }}>
        {window.TS_CATS.map((c, i) => (
          <span key={c} style={{ padding: '8px 16px', borderRadius: 10, fontSize: 13, fontWeight: 600,
            background: i === 0 ? 'linear-gradient(135deg,#5effa0,#1f8a5b)' : 'rgba(255,255,255,.05)',
            color: i === 0 ? '#04130b' : '#aeb6c4', border: '1px solid ' + (i===0?'transparent':'rgba(255,255,255,.08)') }}>{c}</span>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, padding: '0 32px' }}>
        {top.map(d => <ArcCard key={d.id} d={d} />)}
      </div>
    </div>
  );
}
window.ArcadeDashboard = ArcadeDashboard;
