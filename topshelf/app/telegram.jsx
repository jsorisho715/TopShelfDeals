// Telegram bot view — phone chat, live /commands, ranked rows w/ TYPE + Menu + Directions links,
// once-a-day proactive alerts, recurring reminders, weekly digest. Distances use the active location.
const { useState: tgState, useEffect: tgEffect, useRef: tgRef } = React;

function rankRows(rows, loc, n = 6) {
  return [...rows].sort((a, b) => b.score - a.score).slice(0, n);
}

function parseQuery(q, deals) {
  const s = q.toLowerCase();
  const catMap = { flower: 'Flower', bud: 'Flower', preroll: 'Prerolls', prerolls: 'Prerolls', joint: 'Prerolls',
    edible: 'Edibles', edibles: 'Edibles', gummy: 'Edibles', gummies: 'Edibles', hash: 'Concentrates', concentrate: 'Concentrates',
    concentrates: 'Concentrates', rosin: 'Concentrates', dab: 'Concentrates', vape: 'Vapes', vapes: 'Vapes', cart: 'Vapes', carts: 'Vapes' };
  let cat = null; for (const k in catMap) if (s.includes(k)) { cat = catMap[k]; break; }
  const under = s.match(/under\s*\$?\s*(\d+)/);
  const maxUnit = under ? +under[1] : null;
  let r = deals.filter(d => (!cat || d.cat === cat) && (maxUnit == null || d.unit <= maxUnit));
  const area = s.includes('old town') || s.includes('scottsdale') ? 'Scottsdale' : null;
  if (area) r = r.filter(d => d.area === area);
  return { rows: r, cat, maxUnit, area };
}

/* ---- one ranked row: TYPE · product/brand · price · $/u · shop/mi · Menu + Directions links ---- */
const TYPE_ABBR = { Flower: 'FLW', Prerolls: 'PRE', Edibles: 'EDI', Concentrates: 'CONC', Vapes: 'VAPE' };
function RankRow({ d, rank, loc }) {
  const dist = window.getDist(d, loc);
  const Icon = window.CAT_ICON[d.cat] || window.CAT_ICON.All;
  return (
    <div style={{ display: 'flex', gap: 9, padding: '9px 4px', borderBottom: '1px solid rgba(255,255,255,.06)' }}>
      <div style={{ fontFamily: 'Clash Display, sans-serif', fontWeight: 700, fontSize: 15, color: rank === 1 ? '#e8c662' : '#7e9384', width: 16, textAlign: 'center', flexShrink: 0, lineHeight: 1.4 }}>{rank}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
          <div style={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 9, fontWeight: 700, letterSpacing: '.05em', color: '#9fb3a4', background: 'rgba(255,255,255,.06)', border: '1px solid rgba(255,255,255,.1)', borderRadius: 5, padding: '2px 5px', flexShrink: 0 }}>
              <Icon width="10" height="10" />{TYPE_ABBR[d.cat] || d.cat}
            </span>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#fff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.product}</span>
          </div>
          <div style={{ textAlign: 'right', flexShrink: 0 }}>
            <span style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 14, color: '#fff' }}>${d.sale}</span>
            <span style={{ fontSize: 12, color: '#5effa0', fontWeight: 700, marginLeft: 5 }}>−{d.off}%</span>
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', marginTop: 3 }}>
          <span style={{ fontSize: 11, color: '#8aa394', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {d.brand} · {d.shop} · {dist} mi · ${d.unit.toFixed(1)}{d.unitLabel}
          </span>
          <div style={{ display: 'flex', gap: 5, flexShrink: 0 }}>
            <a href={window.specialFor(d)} target="_blank" rel="noopener" style={tgLink}>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><path d="M7 17L17 7M17 7H8M17 7v9"/></svg>Special
            </a>
            <a href={window.mapsDirUrl(d.shop)} target="_blank" rel="noopener" style={{ ...tgLink, color: '#9fc2ff', borderColor: 'rgba(120,170,255,.3)', background: 'rgba(120,170,255,.08)' }}>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M3 11l19-9-9 19-2-8-8-2z"/></svg>Route
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
const tgLink = { display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 10.5, fontWeight: 700, textDecoration: 'none',
  color: '#9af0c4', background: 'rgba(94,255,160,.1)', border: '1px solid rgba(94,255,160,.28)', borderRadius: 7, padding: '3px 7px' };

function RankedList({ deals, loc }) {
  return (
    <div style={{ marginTop: 8, background: 'rgba(0,0,0,.22)', border: '1px solid rgba(255,255,255,.07)', borderRadius: 10, padding: '4px 10px 6px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9.5, fontWeight: 700, letterSpacing: '.08em', color: '#6f8576', textTransform: 'uppercase', padding: '7px 4px 5px', borderBottom: '1px solid rgba(255,255,255,.08)' }}>
        <span>Rank · Type · Item</span><span>Best → worst</span>
      </div>
      {deals.map((d, i) => <RankRow key={d.id} d={d} rank={i + 1} loc={loc} />)}
    </div>
  );
}

function TableBlock() { return null; }

function Bubble({ m, photos, loc }) {
  const me = m.who === 'me';
  const base = { maxWidth: '90%', padding: '10px 13px', borderRadius: 16, fontSize: 13.5, lineHeight: 1.5, position: 'relative' };
  if (me) return (
    <div style={{ alignSelf: 'flex-end', ...base, background: 'linear-gradient(135deg,#2e6f4e,#244f3a)', color: '#eafff2', borderBottomRightRadius: 5 }}>{m.text}
      <span style={{ fontSize: 9.5, color: 'rgba(255,255,255,.6)', marginLeft: 8 }}>{m.time}</span>
    </div>
  );
  const tinted = m.kind === 'reminder' ? { background: 'rgba(212,175,55,.1)', border: '1px solid rgba(212,175,55,.3)' }
    : m.kind === 'alert' ? { background: 'rgba(94,255,160,.07)', border: '1px solid rgba(94,255,160,.25)' }
    : { background: '#1a2632', border: '1px solid rgba(255,255,255,.05)' };
  return (
    <div style={{ alignSelf: 'flex-start', ...base, maxWidth: (m.kind === 'ranked' || m.kind === 'alert' || m.kind === 'digest') ? '98%' : '90%', color: '#e7eef3', borderBottomLeftRadius: 5, ...tinted }}>
      {m.text && <div style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div>}
      {m.kind === 'ranked' && <RankedList deals={m.deals} loc={loc} />}
      {(m.kind === 'alert' || m.kind === 'digest') && m.deals && (
        <div style={{ marginTop: 9, display: 'flex', flexDirection: 'column', gap: 7 }}>
          {m.deals.map(d => <MiniDeal key={d.id} d={d} photo={photos['img-' + d.id]} loc={loc} />)}
        </div>
      )}
      {m.footer && <div style={{ marginTop: 8, fontSize: 11.5, color: '#8aa394' }}>{m.footer}</div>}
      <span style={{ fontSize: 9.5, color: 'rgba(255,255,255,.4)', marginLeft: 8 }}>{m.time}</span>
    </div>
  );
}

function MiniDeal({ d, photo, loc }) {
  const dist = window.getDist(d, loc);
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: 8, borderRadius: 12, background: 'rgba(255,255,255,.05)', border: '1px solid rgba(255,255,255,.08)' }}>
      <div style={{ width: 50, height: 50, flexShrink: 0, borderRadius: 10, overflow: 'hidden' }}>
        <window.ProductShot d={d} img={photo} height={50} radius={10} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 11, color: '#d4af37', fontWeight: 600 }}>{d.brand} · {d.cat}{d.fire ? ' · 🔥' : ''}</div>
        <div style={{ fontSize: 13, color: '#fff', fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.product}</div>
        <div style={{ display: 'flex', gap: 5, marginTop: 3 }}>
          <a href={window.specialFor(d)} target="_blank" rel="noopener" style={tgLink}>Special ↗</a>
          <a href={window.mapsDirUrl(d.shop)} target="_blank" rel="noopener" style={{ ...tgLink, color: '#9fc2ff', borderColor: 'rgba(120,170,255,.3)', background: 'rgba(120,170,255,.08)' }}>Route · {dist}mi</a>
        </div>
      </div>
      <div style={{ textAlign: 'right', flexShrink: 0 }}>
        <div style={{ fontFamily: 'Clash Display', fontWeight: 700, fontSize: 17, color: '#fff' }}>${d.sale}</div>
        <div style={{ fontSize: 12, color: '#5effa0', fontWeight: 700 }}>−{d.off}%</div>
      </div>
    </div>
  );
}

const now = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

function TelegramView({ deals, pings, photos, loc }) {
  const [msgs, setMsgs] = tgState(() => ([
    { who: 'bot', kind: 'text', text: '🌿 TopShelf Bot online. I watch every top-shelf menu within range of your saved location and rank every answer best → worst — each row links straight to the special and to directions.\n\nTry a command below, or ask me e.g. “hash under $25/g near old town”.', time: '9:00 AM' },
    { who: 'bot', kind: 'alert', text: '🔔 Daily alert · 9:00 AM — today’s 🔥 fire deals (new record-low prices, validated against their own history):', deals: rankRows(deals.filter(d => d.fire), 'oldtown', 3), footer: 'Fire = lowest we’ve tracked in 14 days. Deduped — re-alerts only on a deeper drop.', time: '9:00 AM' },
    { who: 'bot', kind: 'reminder', text: '⏰ Tomorrow (Sun): Achieve Live Rosin usually drops to ~$30/g at TruMed. Want a heads-up the moment it’s live?', time: '9:00 AM' },
    { who: 'me', kind: 'text', text: '/deals', time: '9:02 AM' },
    { who: 'bot', kind: 'ranked', text: 'Top qualifying deals right now:', deals: rankRows(deals, loc, 6), footer: 'Tap “Special” for the menu, “Route” for directions.', time: '9:02 AM' },
  ]));
  const scrollRef = tgRef(null);
  const seen = tgRef(0);
  tgEffect(() => { const el = scrollRef.current; if (el) el.scrollTop = el.scrollHeight; }, [msgs]);

  tgEffect(() => {
    if (pings.length > seen.current) {
      const fresh = pings.slice(seen.current); seen.current = pings.length;
      setMsgs(m => [...m, { who: 'bot', kind: 'alert', text: '📌 Saved to your watchlist from the dashboard:', deals: fresh, footer: 'I’ll fold this into tomorrow’s 9 AM daily alert if it’s still live.', time: now() }]);
    }
  }, [pings]);

  const send = (raw) => {
    const q = raw.trim(); if (!q) return;
    setMsgs(m => [...m, { who: 'me', kind: 'text', text: q, time: now() }]);
    setTimeout(() => {
      let reply;
      const cmd = q.toLowerCase().replace('/', '');
      if (cmd === 'digest' || cmd.includes('digest')) {
        reply = { who: 'bot', kind: 'digest', text: '📊 Weekly digest — this week’s best top-shelf deals:', deals: rankRows(deals, loc, 4), footer: 'Upcoming recurring: Wax Sun (Achieve) · Wyld Mon · Jeeter Wed.', time: now() };
      } else if (['deals', 'all', 'best'].includes(cmd)) {
        reply = { who: 'bot', kind: 'ranked', text: 'Top deals:', deals: rankRows(deals, loc, 6), footer: 'Tap “Special” for the menu, “Route” for directions.', time: now() };
      } else {
        const { rows, cat, maxUnit, area } = parseQuery(q, deals);
        if (!rows.length) reply = { who: 'bot', kind: 'text', text: 'No qualifying deals match that right now. Try loosening the price or distance.', time: now() };
        else reply = { who: 'bot', kind: 'ranked', text: `${cat || 'Deals'}${maxUnit ? ` under $${maxUnit}/u` : ''}${area ? ` · ${area}` : ''}:`, deals: rankRows(rows, loc, 6), footer: `${rows.length} match · ranked by deal score`, time: now() };
      }
      setMsgs(m => [...m, reply]);
    }, 460);
  };

  const [input, setInput] = tgState('');
  const quick = ['/deals', '/flower', '/hash', '/edibles', '/vapes', '/prerolls', '/digest', 'hash under $25/g'];
  const locLabel = (window.TS_LOCATIONS.find(l => l.id === loc) || window.TS_LOCATIONS[0]).label;

  return (
    <div className="ts-tg-wrap" style={{ display: 'flex', gap: 40, alignItems: 'center', justifyContent: 'center', padding: '20px 0 60px', flexWrap: 'wrap' }}>
      <div className="ts-tg-aside" style={{ maxWidth: 340 }}>
        <div style={{ fontSize: 11.5, letterSpacing: '.22em', textTransform: 'uppercase', color: '#7e9384', marginBottom: 12 }}>Your pocket dealfinder</div>
        <h2 style={{ fontFamily: 'Clash Display', fontWeight: 600, fontSize: 38, lineHeight: 1.02, letterSpacing: '-.02em', margin: 0 }}>
          Every reply is a <span style={{ color: '#d4af37' }}>ranked table</span> with links to the special.
        </h2>
        <p style={{ color: '#a9bcae', fontSize: 14.5, lineHeight: 1.6, marginTop: 16 }}>
          Best → worst, every time. Each row links to the dispensary’s live menu and to turn-by-turn directions. Ask in plain English or fire a slash-command.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 20 }}>
          {[['🔔', 'One alert a day', 'New qualifying deals batched into a single 9 AM message — never per-deal spam.'],
            ['↻', 'Recurring memory', 'Learns each shop’s themed days and reminds you ahead.'],
            ['📊', 'Sunday digest', 'The week’s best + what’s coming, every Sunday evening.']].map(([i, t, s]) => (
            <div key={t} style={{ display: 'flex', gap: 12, padding: 12, borderRadius: 14, background: 'rgba(255,255,255,.03)', border: '1px solid rgba(255,255,255,.07)' }}>
              <span style={{ fontSize: 18 }}>{i}</span>
              <div><div style={{ fontWeight: 700, fontSize: 13.5, color: '#eaf2eb' }}>{t}</div><div style={{ fontSize: 12.5, color: '#8fa496' }}>{s}</div></div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 18, fontSize: 12, color: '#7e9384' }}>Tip: on the dashboard, hit <b style={{ color: '#cbd8cc' }}>Ping</b> on any card → it arrives here.</div>
      </div>

      {/* phone */}
      <div style={{ width: 384, maxWidth: '94vw', height: 'min(800px, 86vh)', borderRadius: 46, padding: 12, flexShrink: 0,
        background: 'linear-gradient(160deg,#23282e,#0c0e11)', boxShadow: '0 50px 100px -30px rgba(0,0,0,.9), 0 0 0 2px rgba(255,255,255,.06) inset' }}>
        <div style={{ position: 'relative', height: '100%', borderRadius: 36, overflow: 'hidden', background: '#0e1621', display: 'flex', flexDirection: 'column' }}>
          <div style={{ position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)', width: 120, height: 26, background: '#0c0e11', borderRadius: 16, zIndex: 10 }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '40px 16px 12px', background: 'linear-gradient(180deg,#17212b,#141d26)', borderBottom: '1px solid rgba(0,0,0,.4)' }}>
            <div style={{ width: 40, height: 40, borderRadius: 22, background: 'linear-gradient(135deg,#e8c662,#1f8a5b)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#0a1610', fontFamily: 'Clash Display', fontWeight: 700, fontSize: 19 }}>T</div>
            <div style={{ flex: 1 }}>
              <div style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>TopShelf Bot</div>
              <div style={{ color: '#5effa0', fontSize: 12 }}>● near {locLabel} · online</div>
            </div>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#6f8190" strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>
          </div>

          <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '14px 12px', display: 'flex', flexDirection: 'column', gap: 9,
            background: 'linear-gradient(180deg,#0e1621,#0b121a)' }}>
            {msgs.map((m, i) => <Bubble key={i} m={m} photos={photos} loc={loc} />)}
          </div>

          <div style={{ display: 'flex', gap: 6, padding: '8px 10px 4px', overflowX: 'auto', background: '#0e1621' }}>
            {quick.map(c => (
              <button key={c} onClick={() => send(c)} style={{ flexShrink: 0, padding: '6px 12px', borderRadius: 16, fontSize: 12, fontFamily: c.startsWith('/') ? 'JetBrains Mono, monospace' : 'Satoshi', fontWeight: 600,
                border: '1px solid rgba(94,255,160,.25)', background: 'rgba(94,255,160,.08)', color: '#9af0c4', cursor: 'pointer', whiteSpace: 'nowrap' }}>{c}</button>
            ))}
          </div>

          <form onSubmit={e => { e.preventDefault(); send(input); setInput(''); }} style={{ display: 'flex', gap: 8, padding: '8px 12px 14px', background: '#0e1621' }}>
            <input value={input} onChange={e => setInput(e.target.value)} placeholder="Ask for a deal…" style={{ flex: 1, padding: '11px 14px', borderRadius: 22, border: '1px solid rgba(255,255,255,.1)', background: '#17212b', color: '#fff', fontSize: 13.5, fontFamily: 'Satoshi', outline: 'none' }} />
            <button type="submit" style={{ width: 42, height: 42, borderRadius: 22, border: 'none', cursor: 'pointer', background: 'linear-gradient(135deg,#5effa0,#1f8a5b)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#04130b" strokeWidth="2.4"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
window.TelegramView = TelegramView;
