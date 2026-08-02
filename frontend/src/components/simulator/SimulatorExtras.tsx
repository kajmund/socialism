import { useEffect, useState, type CSSProperties } from "react";
import { MESSAGE_PROFILES, PERSONAS } from "@/data/mock";


type ResponsePreviewProps = { msgA: string; msgB: string }
type MiniDriftProps = { values: number[]; color: string; hours: number[] }
type ABCompareCardProps = {
  profile: (typeof MESSAGE_PROFILES)["a"]
  side: string
  msgText: string
  hours: number[]
}
type ABCompareProps = { msgA: string; msgB: string; hours: number[] }
type StoryModeProps = {
  onStepChange: (step: number) => void
  onEnd: () => void
}

/* ─────────────────────────────────────────────────────────────
   Step 3 — Response preview
   ───────────────────────────────────────────────────────────── */
export function ResponsePreview({ msgA, msgB }: ResponsePreviewProps) {
  const picks = [0, 5, 6]; // Margareta, Hassan, Eva — strong contrast
  const [revealed, setRevealed] = useState(false);
  const ready = msgA.trim().length > 10 && msgB.trim().length > 10;

  useEffect(() => {
    if (!ready) { setRevealed(false); return; }
    const t = setTimeout(() => setRevealed(true), 250);
    return () => clearTimeout(t);
  }, [msgA, msgB, ready]);

  if (!ready) return null;

  return (
    <div className="preview-wrap">
      <div className="preview-head">
        <div>
          <div className="lbl">Förhandsgranskning</div>
          <h2>Hur 3 av agenterna troligen skulle reagera</h2>
          <div className="sub">Detta är inte den fulla simuleringen — bara en snabb läsning på tre kontrasterande personas innan du går vidare. Klicka "Kör simulering" för att aktivera hela populationen.</div>
        </div>
      </div>

      <div className="preview-grid">
        {picks.map((i, k) => {
          const p = PERSONAS[i];
          return (
            <div
              key={i}
              className="card preview-card"
              style={{
                opacity: revealed ? 1 : 0,
                transform: revealed ? "translateY(0)" : "translateY(6px)",
                transition: `opacity .4s ${k * 0.1}s, transform .4s ${k * 0.1}s`,
              }}
            >
              <div className="pv-head">
                <div className="avatar" style={{background: p.color, width: 38, height: 38, fontSize: 14}}>{p.initials}</div>
                <div>
                  <div className="nm">{p.name}</div>
                  <div className="sub">{p.age} år · {p.district}</div>
                </div>
              </div>

              <div className="pv-bubble a">
                <span className="pv-tag">På budskap A · {p.reactA.tone}</span>
                <div>"{p.reactA.text}"</div>
                <div className="pv-action" style={{marginTop:6}}>→ {p.reactA.action}</div>
              </div>

              <div className="pv-bubble b">
                <span className="pv-tag">På budskap B · {p.reactB.tone}</span>
                <div>"{p.reactB.text}"</div>
                <div className="pv-action" style={{marginTop:6}}>→ {p.reactB.action}</div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="preview-disclaimer">
        Förhandsreaktioner är genererade utifrån personas profil — den fulla simuleringen mäter spridning, opinionsledare och ämnesdrift över hela populationen.
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Step 5 — A/B side-by-side comparison
   ───────────────────────────────────────────────────────────── */
export function MiniDrift({ values, color, hours }: MiniDriftProps) {
  const W = 280, H = 100, P = 12;
  const max = 100;
  const x = (i: number) => P + (i / (hours.length - 1)) * (W - P * 2);
  const y = (v: number) => H - P - (v / max) * (H - P * 2);
  const d = values.map((v, j) => `${j === 0 ? "M" : "L"} ${x(j)} ${y(v)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width: "100%", height: 100}}>
      {[0, 50, 100].map((g, i) => (
        <line key={i} x1={P} y1={y(g)} x2={W-P} y2={y(g)} stroke="#C9BC9F" strokeDasharray="2 3" strokeWidth="1" />
      ))}
      <path d={d} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" />
      {hours.map((h, i) => (
        <text key={i} x={x(i)} y={H - 1} textAnchor="middle" fontSize="9" fill="#A89D87">{h}h</text>
      ))}
    </svg>
  );
}

export function ABCompareCard({ profile, side, msgText, hours }: ABCompareCardProps) {
  return (
    <div className={"card ab-card " + side}>
      <div className="ab-head">
        <div>
          <div className="ab-name">{profile.label}</div>
          <div className="ab-style">{profile.style}</div>
        </div>
      </div>

      <div className="ab-excerpt">"{(msgText && msgText.length > 20) ? msgText.slice(0, 180) + (msgText.length > 180 ? "…" : "") : profile.excerpt}"</div>

      <div className="ab-stats">
        <div className="ab-stat"><div className="n">{profile.avgEngagement}%</div><div className="l">Snitt engagemang</div></div>
        <div className="ab-stat"><div className="n">{profile.reach.toLocaleString("sv-SE")}</div><div className="l">Personer nådda</div></div>
        <div className="ab-stat"><div className="n">{profile.sharedBy}</div><div className="l">Delningar</div></div>
      </div>

      <div className="ab-section">
        <div className="l">Toppengagemang — personas</div>
        <div className="ab-top">
          {profile.topPersonas.map((p, i) => (
            <div className="ab-top-row" key={i}>
              <div className="avatar" style={{background: p.color}}>{p.initials}</div>
              <div className="nm">{p.who}</div>
              <div className="v">{p.v}%</div>
            </div>
          ))}
        </div>
      </div>

      <div className="ab-section">
        <div className="l">Dominerande sub-tema (24h)</div>
        <div style={{fontFamily: "var(--font-display)", fontSize: 18}}>{profile.dominantTopic}</div>
        <div style={{marginTop: 12}} className="ab-drift">
          <MiniDrift values={profile.driftSecondary.values} color={profile.driftSecondary.color} hours={hours} />
        </div>
        <div className="small muted" style={{marginTop: 4}}>{profile.driftSecondary.name}</div>
      </div>

      <div className="ab-section">
        <div className="l">Karakteristisk reaktion</div>
        <div className="ab-quote">
          {profile.characteristicQuote}
          <span className="who">— {profile.characteristicWho}</span>
        </div>
      </div>

      <div className="ab-section">
        <div className="l">Vinner hos</div>
        <div style={{fontSize: 15, color: "var(--ink-2)"}}>{profile.audience}</div>
      </div>
    </div>
  );
}

export function ABCompare({ msgA, msgB, hours }: ABCompareProps) {
  return (
    <div className="ab-grid">
      <ABCompareCard profile={MESSAGE_PROFILES.a} side="a" msgText={msgA} hours={hours} />
      <ABCompareCard profile={MESSAGE_PROFILES.b} side="b" msgText={msgB} hours={hours} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Export button
   ───────────────────────────────────────────────────────────── */
export function ExportButton() {
  const [state, setState] = useState("idle"); // idle | loading | done
  const [toast, setToast] = useState(false);

  function click() {
    if (state !== "idle") return;
    setState("loading");
    setTimeout(() => {
      setState("done");
      setToast(true);
      setTimeout(() => setToast(false), 3200);
      setTimeout(() => setState("idle"), 4000);
    }, 1100);
  }

  return (
    <>
      <button className={"btn-export " + state} onClick={click}>
        {state === "loading" && (<><span className="spin"></span>Genererar PDF…</>)}
        {state === "done" && (<>✓ Rapport exporterad</>)}
        {state === "idle" && (<>↓ Exportera resultatrapport</>)}
      </button>
      {toast && (
        <div className="export-toast">
          <span className="check">✓</span>
          <span>Resultatrapport_norrkoping_240429.pdf · 14 sidor</span>
        </div>
      )}
    </>
  );
}

/* ─────────────────────────────────────────────────────────────
   Story mode (guided demo)
   ───────────────────────────────────────────────────────────── */
const STORY_TIPS = [
  { step: 1, title: "Steg 1 — Välj population", body: "Här bestämmer ni vilken sammansättning av medborgare ni vill testa budskapen mot. Norrköping realistisk är pilotpopulationen baserad på SCB-data.", dur: 6000 },
  { step: 2, title: "Steg 2 — Granska personas", body: "Varje persona är förankrad i Norrköping — stadsdel, yrke, retorisk stil. 'Vet om Norrköping'-fältet visar exakt vilken lokal kunskap modellen är grundad i.", dur: 7000 },
  { step: 3, title: "Steg 3 — Skriv budskap A och B", body: "Två varianter av samma budskap. Förhandsgranskningen visar genast hur tre kontrasterande personas troligen skulle reagera — innan ni kör hela simuleringen.", dur: 7500 },
  { step: 4, title: "Steg 4 — Konfigurera scenario", body: "Hur lång period ska simuleras? Ska vi störa flödet med en konkurrerande nyhet? Verkligheten är sällan en lugn vik.", dur: 6500 },
  { step: 5, title: "Steg 5 — Resultat", body: "Det här är värdet: vilket budskap vann, hos vem, var i kommunen, och varför. Växla mellan sammanfattning och A/B sida-vid-sida för att se hela skillnaden.", dur: 9000 },
];

export function StoryMode({ onStepChange, onEnd }: StoryModeProps) {
  const [idx, setIdx] = useState(0);
  const [paused, setPaused] = useState(false);
  const tip = STORY_TIPS[idx];

  useEffect(() => {
    onStepChange(tip.step);
  }, [idx, tip.step, onStepChange]);

  useEffect(() => {
    if (paused) return;
    const t = setTimeout(() => {
      if (idx + 1 >= STORY_TIPS.length) {
        onEnd();
      } else {
        setIdx(idx + 1);
      }
    }, tip.dur);
    return () => clearTimeout(t);
  }, [idx, paused, tip.dur, onEnd]);

  return (
    <>
      <div className="story-vignette"></div>
      <div className="story-card">
        <div className="sc-top">
          <span className="sc-step">Guidad demo · {idx+1} / {STORY_TIPS.length}</span>
          <div className="sc-controls">
            <button className="sc-btn" onClick={() => setPaused(p => !p)}>{paused ? "▶ Fortsätt" : "❚❚ Pausa"}</button>
            <button className="sc-btn" onClick={() => idx + 1 >= STORY_TIPS.length ? onEnd() : setIdx(idx + 1)}>Nästa →</button>
            <button className="sc-btn" onClick={onEnd}>Avsluta</button>
          </div>
        </div>
        <h3>{tip.title}</h3>
        <p>{tip.body}</p>
        <div className="story-progress">
          {STORY_TIPS.map((_, i) => (
            <div
              key={i}
              className={"dot " + (i < idx ? "done" : i === idx && !paused ? "active" : "")}
              style={{ ["--story-dur"]: `${tip.dur}ms` } as CSSProperties}
            ></div>
          ))}
        </div>
      </div>
    </>
  );
}

