import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  DISTRICTS,
  LOCAL_CONTEXT,
  NEWS_OPTIONS,
  PERSONAS,
  POPULATIONS,
  RESULTS,
  TIME_OPTIONS,
} from "@/data/mock";
import {
  ABCompare,
  ExportButton,
  ResponsePreview,
  StoryMode,
} from "@/components/simulator/SimulatorExtras";


type StepperProps = { step: number; maxReached: number; onJump: (s: number) => void }
type StepPopulationProps = { value: string; onChange: (id: string) => void }
type StepPersonasProps = { activeIdx: number; onActiveChange: (i: number) => void }
type StepMessagesProps = {
  msgA: string
  msgB: string
  setMsgA: (v: string) => void
  setMsgB: (v: string) => void
}
type StepScenarioProps = {
  time: string
  setTime: (v: string) => void
  news: boolean
  setNews: (v: boolean) => void
  newsType: string
  setNewsType: (v: string) => void
}
type HeatmapProps = { onPersonaJump?: (p: (typeof PERSONAS)[number]) => void }
type DriftChartProps = { drift: typeof RESULTS.drift }
type StepResultsProps = {
  onRestart: () => void
  scenario: { popName?: string; timeLabel?: string; news: boolean; newsType: string }
  msgA: string
  msgB: string
  onPersonaJump: (p: (typeof PERSONAS)[number]) => void
}
type RunOverlayProps = { onDone: () => void }

/* ─────────────────────────────────────────────────────────────
   Stepper
   ───────────────────────────────────────────────────────────── */
function Stepper({ step, maxReached, onJump }: StepperProps) {
  const steps = [
    { num: "01", title: "Population" },
    { num: "02", title: "Personas" },
    { num: "03", title: "Budskap A / B" },
    { num: "04", title: "Scenario" },
    { num: "05", title: "Resultat" },
  ];
  return (
    <div className="stepper">
      {steps.map((s, i) => {
        const idx = i + 1;
        const active = idx === step;
        const done = idx < step;
        const reachable = idx <= maxReached;
        return (
          <button
            key={i}
            className={"step-pill " + (active ? "active " : "") + (done ? "done " : "") + (!reachable ? "disabled" : "")}
            onClick={() => reachable && onJump(idx)}
            disabled={!reachable}
          >
            <span className="step-num"><span>{s.num}</span></span>
            <span className="step-label">
              <span className="kicker">Steg {s.num}</span>
              <span className="title">{s.title}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Step 1: Population
   ───────────────────────────────────────────────────────────── */
function StepPopulation({ value, onChange }: StepPopulationProps) {
  return (
    <>
      <div className="section-head">
        <div className="kicker">Steg 1 av 5</div>
        <h1>Välj population</h1>
        <p>Vilken sammansättning av medborgare ska vi testa budskapen mot? Varje profil består av AI-agenter som spelar individer med egen historik, åsikt och stil.</p>
      </div>
      <div className="pop-grid">
        {POPULATIONS.map(p => (
          <div
            key={p.id}
            className={"card clickable pop-card " + (value === p.id ? "selected" : "")}
            onClick={() => onChange(p.id)}
          >
            <span className="pop-tag">{p.tag}</span>
            <div>
              <h3>{p.name}</h3>
              <div className="pop-desc" style={{marginTop:6}}>{p.desc}</div>
            </div>
            <div>
              <div className="pop-bar">
                {p.distribution.map((d, i) => (
                  <div key={i} style={{width: d.pct + "%", background: d.color}} title={`${d.label} — ${d.pct}%`}></div>
                ))}
              </div>
              <div className="pop-legend" style={{marginTop:14}}>
                {p.distribution.map((d, i) => (
                  <div key={i}>
                    <span className="dot" style={{background: d.color}}></span>
                    <span>{d.label} <span className="muted">{d.pct}%</span></span>
                  </div>
                ))}
              </div>
            </div>
            <div className="pop-stats">
              <div className="pop-stat">
                <div className="n">{p.n.toLocaleString("sv-SE")}</div>
                <div className="l">Agenter</div>
              </div>
              {p.stats.map((s, i) => (
                <div className="pop-stat" key={i}>
                  <div className="n">{s.n}</div>
                  <div className="l">{s.l}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="context-callout">
        <h3>Vad agenterna vet om Norrköping</h3>
        <div className="ck-sub">{LOCAL_CONTEXT.summary}</div>
        <div className="context-grid">
          {LOCAL_CONTEXT.layers.map((l, i) => (
            <div key={i} className={"row " + (i === LOCAL_CONTEXT.layers.length - 1 ? "warn" : "")}>
              <span className="l">{l.lbl}</span>
              <span className="v">{l.val}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────
   Step 2: Personas
   ───────────────────────────────────────────────────────────── */
function StepPersonas({ activeIdx, onActiveChange }: StepPersonasProps) {
  const p = PERSONAS[activeIdx];
  return (
    <>
      <div className="section-head">
        <div className="kicker">Steg 2 av 5</div>
        <h1>Inspektera personas</h1>
        <p>8 exempel-agenter ur den valda populationen. Var och en har en egen biografi, retorisk stil och politisk lutning. Klicka för att läsa profilen.</p>
      </div>
      <div className="persona-grid">
        <div className="persona-list">
          {PERSONAS.map((x, i) => (
            <div
              key={i}
              className={"persona-row " + (i === activeIdx ? "active" : "")}
              onClick={() => onActiveChange(i)}
            >
              <div className="avatar" style={{background: x.color}}>{x.initials}</div>
              <div>
                <div className="nm">{x.name}</div>
                <div className="mt">{x.age} år · {x.district}</div>
              </div>
            </div>
          ))}
        </div>

        <div className="card persona-detail">
          <div className="head">
            <div className="avatar" style={{background: p.color}}>{p.initials}</div>
            <div>
              <h2>{p.name}</h2>
              <div className="sub">{p.age} år · {p.occupation} · {p.district}</div>
            </div>
          </div>

          <div className="persona-grid-stats">
            <div className="row">
              <div className="l">Politisk sympati</div>
              <div className="v">{p.party}</div>
            </div>
            <div className="row">
              <div className="l">Politisk lutning</div>
              <div className="v">{p.leaning}</div>
            </div>
            <div className="row" style={{gridColumn: "1 / -1"}}>
              <div className="l">Retorisk stil</div>
              <div className="v">{p.style}</div>
            </div>
          </div>

          <div>
            <div className="l small muted" style={{textTransform:"uppercase", letterSpacing:".08em", margin:"22px 0 12px"}}>Personlighetsdrag</div>
            <div className="traits" style={{padding:0, border:"none"}}>
              {p.traits.map((t, i) => <span className="trait" key={i}>{t}</span>)}
            </div>
          </div>

          {p.knows && (
            <div className="knows-section">
              <div className="knows-label">Vet om Norrköping</div>
              <div className="knows-list">
                {p.knows.map((k, i) => <span className="know-chip" key={i}>{k}</span>)}
              </div>
            </div>
          )}

          <div className="quote">
            <span className="lbl">Exempelreplik</span>
            "{p.quote}"
          </div>
        </div>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────
   Step 3: Messages
   ───────────────────────────────────────────────────────────── */
const MSG_TEMPLATES: Record<"a" | "b", string[]> = {
  a: [
    "Vi måste investera i äldreomsorgen. Sverige förtjänar trygghet på äldre dar och en värdig omsorg för alla. Det är en principfråga om rättvisa.",
    "Det är dags att stå upp för välfärden. Vi vägrar acceptera att äldreomsorgen prioriteras bort. Vår politik bygger på solidaritet — för alla, hela livet.",
  ],
  b: [
    "Eva på Vrinnevi jobbar tredje natten i rad. Margareta i Hageby har väntat två veckor på en utredning. Vi tillsätter 200 nya undersköterskor i Norrköping under första året.",
    "Förra veckan träffade jag Hassan som körde sin mamma till akuten — och fick vänta i fem timmar. Det är inte okej. Vi anställer 200 fler i vården. På riktigt. I år.",
  ],
};

function StepMessages({ msgA, msgB, setMsgA, setMsgB }: StepMessagesProps) {
  return (
    <>
      <div className="section-head">
        <div className="kicker">Steg 3 av 5</div>
        <h1>Skriv två versioner av samma budskap</h1>
        <p>A och B ska handla om samma sak men formuleras olika. Det är skillnaden mellan dem simuleringen mäter.</p>
      </div>
      <div className="msg-grid">
        {([
          { key: "a" as const, value: msgA, set: setMsgA, badge: "Budskap A", placeholder: "Klistra in eller skriv version A här…" },
          { key: "b" as const, value: msgB, set: setMsgB, badge: "Budskap B", placeholder: "Klistra in eller skriv version B här…" },
        ]).map(m => (
          <div className={"card msg-card " + m.key} key={m.key}>
            <span className="badge">{m.badge}</span>
            <label>Texten du vill publicera</label>
            <textarea value={m.value} onChange={e => m.set(e.target.value)} placeholder={m.placeholder} />
            <div className="meta">
              <span>{m.value.length} tecken</span>
              <span>{m.value.trim() ? m.value.trim().split(/\s+/).length : 0} ord</span>
            </div>
            <div style={{marginTop:6}}>
              <div className="l small muted" style={{textTransform:"uppercase", letterSpacing:".08em", marginBottom:8}}>Förslag att utgå från</div>
              <div className="suggest-row">
                {MSG_TEMPLATES[m.key].map((t: string, i: number) => (
                  <button className="suggest-chip" key={i} onClick={() => m.set(t)}>
                    Förslag {i+1}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      <ResponsePreview msgA={msgA} msgB={msgB} />
    </>
  );
}

/* ─────────────────────────────────────────────────────────────
   Step 4: Scenario
   ───────────────────────────────────────────────────────────── */
function StepScenario({ time, setTime, news, setNews, newsType, setNewsType }: StepScenarioProps) {
  return (
    <>
      <div className="section-head">
        <div className="kicker">Steg 4 av 5</div>
        <h1>Konfigurera scenario</h1>
        <p>Hur lång period ska simuleras, och ska vi störa flödet med en konkurrerande händelse? Verkligheten är sällan en lugn vik.</p>
      </div>
      <div className="scenario-grid">
        <div className="card scenario-card">
          <h3>Tidsperiod</h3>
          <div className="muted small" style={{marginBottom:18}}>Hur många dygn av reaktioner och samtal vill du simulera?</div>
          <div className="time-options">
            {TIME_OPTIONS.map(o => (
              <div
                key={o.id}
                className={"opt-row " + (time === o.id ? "sel" : "")}
                onClick={() => setTime(o.id)}
              >
                <div className="opt-radio"></div>
                <div className="opt-body">
                  <div className="opt-label">{o.label}</div>
                  <div className="opt-desc">{o.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card scenario-card">
          <h3>Störande nyhet</h3>
          <div className="muted small" style={{marginBottom:18}}>Inject en konkurrerande händelse halvvägs in i simuleringen.</div>
          <div className="toggle-row">
            <div>
              <div style={{fontWeight:600}}>Aktivera nyhetsstörning</div>
              <div className="small muted">Av — rent budskapstest utan brus</div>
            </div>
            <div className={"toggle " + (news ? "on" : "")} onClick={() => setNews(!news)}></div>
          </div>
          <div className="time-options" style={{marginTop:18, opacity: news ? 1 : .4, pointerEvents: news ? "auto" : "none"}}>
            {NEWS_OPTIONS.filter(n => n.id !== "none").map(o => (
              <div
                key={o.id}
                className={"opt-row " + (newsType === o.id ? "sel" : "")}
                onClick={() => setNewsType(o.id)}
              >
                <div className="opt-radio"></div>
                <div className="opt-body">
                  <div className="opt-label">{o.label}</div>
                  <div className="opt-desc">{o.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────
   Step 5: Results
   ───────────────────────────────────────────────────────────── */
/* ─────────────────────────────────────────────────────────────
   Heatmap (stadsdelar)
   ───────────────────────────────────────────────────────────── */
function lerp(a: number, b: number, t: number) { return Math.round(a + (b - a) * t); }

function heatColor(val: number, mode: string) {
  if (mode === "diff") {
    const v = Math.max(-50, Math.min(50, val)) / 50;
    if (v >= 0) {
      const t = v;
      return `rgb(${lerp(242,201,t)}, ${lerp(234,107,t)}, ${lerp(216,58,t)})`;
    } else {
      const t = -v;
      return `rgb(${lerp(242,30,t)}, ${lerp(234,58,t)}, ${lerp(216,85,t)})`;
    }
  }
  const t = Math.max(0, Math.min(100, val)) / 100;
  if (mode === "a") {
    return `rgb(${lerp(242,30,t)}, ${lerp(234,58,t)}, ${lerp(216,85,t)})`;
  } else {
    return `rgb(${lerp(242,201,t)}, ${lerp(234,107,t)}, ${lerp(216,58,t)})`;
  }
}

function Heatmap({ onPersonaJump }: HeatmapProps) {
  const [mode, setMode] = useState("diff");

  const personaById = useMemo(() => {
    const m: Record<string, (typeof PERSONAS)[number]> = {};
    PERSONAS.forEach(p => { m[p.initials] = p; });
    return m;
  }, []);

  function cellValue(d: (typeof DISTRICTS)[number]) {
    if (mode === "a") return d.engA;
    if (mode === "b") return d.engB;
    return d.engB - d.engA;
  }
  function cellLabel(d: (typeof DISTRICTS)[number]) {
    const v = cellValue(d);
    if (mode === "diff") return (v >= 0 ? "+" : "") + v;
    return v + "%";
  }
  function cellTone(d: (typeof DISTRICTS)[number]) {
    const v = cellValue(d);
    if (mode === "diff") return Math.abs(v) > 25 ? "dark" : "light";
    return v > 50 ? "dark" : "light";
  }

  const topB = [...DISTRICTS].sort((a, b) => (b.engB - b.engA) - (a.engB - a.engA))[0];
  const topA = [...DISTRICTS].sort((a, b) => (a.engB - a.engA) - (b.engB - b.engA))[0];
  const avgDiff = Math.round(DISTRICTS.reduce((s, d) => s + (d.engB - d.engA), 0) / DISTRICTS.length);

  const gradA = `linear-gradient(to right, rgb(242,234,216), rgb(30,58,85))`;
  const gradB = `linear-gradient(to right, rgb(242,234,216), rgb(201,107,58))`;
  const gradDiff = `linear-gradient(to right, rgb(30,58,85), rgb(242,234,216), rgb(201,107,58))`;

  return (
    <div className="card heatmap-card">
      <div className="heat-head">
        <div>
          <h3>Engagemang per stadsdel</h3>
          <div className="sub">{DISTRICTS.length} stadsdelar i Norrköpings kommun. Mörkare = starkare reaktion. Prickar markerar var de namngivna personas bor.</div>
        </div>
        <div className="heat-toggle">
          <button className={mode === "a" ? "on" : ""} onClick={() => setMode("a")}>Budskap A</button>
          <button className={mode === "b" ? "on" : ""} onClick={() => setMode("b")}>Budskap B</button>
          <button className={mode === "diff" ? "on" : ""} onClick={() => setMode("diff")}>Differens (B − A)</button>
        </div>
      </div>

      <div className="heat-grid">
        {DISTRICTS.map(d => {
          const persona = d.persona ? personaById[d.persona] : null;
          return (
            <div
              key={d.id}
              className={"heat-cell " + cellTone(d)}
              style={{ background: heatColor(cellValue(d), mode) }}
              title={`${d.name} — A: ${d.engA}%, B: ${d.engB}%`}
            >
              <div className="nm">{d.name}</div>
              <div className="v">{cellLabel(d)}</div>
              {persona && (
                <div
                  className="persona-dot"
                  style={{background: persona.color}}
                  title={`${persona.name} — klicka för profil`}
                  onClick={() => onPersonaJump && onPersonaJump(persona)}
                >
                  {persona.initials}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="heat-scale">
        <div className="heat-scale-block">
          <div className="bar" style={{ background: mode === "a" ? gradA : mode === "b" ? gradB : gradDiff }}></div>
          <div className="lbl-row">
            {mode === "diff"
              ? <><span>A vinner −50</span><span>0</span><span>+50 B vinner</span></>
              : <><span>0% engagemang</span><span>100%</span></>}
          </div>
        </div>
        <div style={{fontFamily:"var(--font-display)", fontSize:13, color:"var(--ink-3)", fontStyle:"italic", maxWidth:280}}>
          {mode === "diff" && "Orange = budskap B vann området. Blå = A vann."}
          {mode === "a" && "Blå intensitet visar engagemangsnivå för budskap A."}
          {mode === "b" && "Orange intensitet visar engagemangsnivå för budskap B."}
        </div>
      </div>

      <div className="heat-insights">
        <div className="heat-insight">
          <div className="l">Tydligaste vinst för B</div>
          <div className="v"><em>{topB.name}</em> — B vinner med {topB.engB - topB.engA} procentenheter</div>
        </div>
        <div className="heat-insight">
          <div className="l">Bästa område för A</div>
          <div className="v"><em>{topA.name}</em> — A vinner med {topA.engA - topA.engB} procentenheter</div>
        </div>
        <div className="heat-insight">
          <div className="l">Genomsnittlig skillnad</div>
          <div className="v">B leder i snitt med <em>+{avgDiff} pp</em> över hela kommunen</div>
        </div>
        <div className="heat-insight">
          <div className="l">Mönster</div>
          <div className="v">B dominerar i <em>arbetarklass-förorter</em>. A håller bara <em>centrala och akademiska</em> områden.</div>
        </div>
      </div>
    </div>
  );
}

function DriftChart({ drift }: DriftChartProps) {
  const W = 520, H = 240, P = 28;
  const xs = drift.hours;
  const xMax = xs[xs.length - 1];
  const x = (h: number) => P + (h / xMax) * (W - P * 2);
  const y = (v: number) => H - P - (v / 100) * (H - P * 2);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="drift-chart">
      {/* grid */}
      {[0, 25, 50, 75, 100].map((g, i) => (
        <g key={i}>
          <line x1={P} y1={y(g)} x2={W - P} y2={y(g)} stroke="#C9BC9F" strokeDasharray="2 3" strokeWidth="1" />
          <text x={P - 6} y={y(g) + 4} textAnchor="end" fontSize="10" fill="#A89D87">{g}</text>
        </g>
      ))}
      {/* x axis labels */}
      {xs.map((h, i) => (
        <text key={i} x={x(h)} y={H - 8} textAnchor="middle" fontSize="11" fill="#6B6253">{h}h</text>
      ))}
      {/* lines */}
      {drift.topics.map((t, i) => {
        const d = t.values.map((v, j) => `${j === 0 ? "M" : "L"} ${x(xs[j])} ${y(v)}`).join(" ");
        return <path key={i} d={d} fill="none" stroke={t.color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />;
      })}
      {/* end dots */}
      {drift.topics.map((t, i) => (
        <circle key={i} cx={x(xs[xs.length-1])} cy={y(t.values[t.values.length-1])} r="3.5" fill={t.color} />
      ))}
    </svg>
  );
}

function StepResults({ onRestart, scenario, msgA, msgB, onPersonaJump }: StepResultsProps) {
  const R = RESULTS;
  const [mode, setMode] = useState("summary"); // summary | ab
  return (
    <>
      <div className="section-head">
        <div className="kicker">Steg 5 av 5 · Simulering klar</div>
        <h1>Resultat</h1>
        <p>Sammanfattning av {(scenario.timeLabel ?? "").toLowerCase()} simulerad konversation kring de två budskapen.</p>
      </div>

      <div className="results-mode-toggle">
        <button className={mode === "summary" ? "on" : ""} onClick={() => setMode("summary")}>Sammanfattning</button>
        <button className={mode === "ab" ? "on" : ""} onClick={() => setMode("ab")}>A vs B sida-vid-sida</button>
      </div>

      {mode === "ab" && (
        <div style={{marginBottom: 22}}>
          <ABCompare msgA={msgA} msgB={msgB} hours={R.drift.hours} />
        </div>
      )}

      {mode === "summary" && (
      <div className="results-grid">
        {/* Winner */}
        <div className="winner-card pres-highlight">
          <div style={{textAlign:"center"}}>
            <div className="lbl">Vinnande budskap</div>
            <div className="nm">{R.winner}</div>
            <div className="pill">+{R.winnerMargin} pp engagemang</div>
          </div>
          <div>
            <div className="lbl">Vinnande stilegenskap</div>
            <h2 style={{fontSize:28, color:"var(--paper)", marginBottom:10}}>{R.winnerStyle}</h2>
            <div className="desc">Förlorande stil: <em>{R.loserStyle}</em>. Skillnaden var som störst i ålderskohorten 55+ och i Hageby/Berga/Navestad. Akademiker (Klockaretorpet, Centrum) föredrog A.</div>
          </div>
        </div>

        {/* Two columns: engagement + leaders */}
        <div className="results-2col">
          <div className="card chart-card">
            <h3>Engagemang per persona</h3>
            <div className="sub">Andel av kohorten som engagerade sig (delade, kommenterade, gillade).</div>
            <div className="legend-row">
              <span className="lg"><span className="sw" style={{background:"var(--primary)"}}></span>Budskap A</span>
              <span className="lg"><span className="sw" style={{background:"var(--warm-orange)"}}></span>Budskap B</span>
            </div>
            <div className="eng-grid">
              {R.engagement.map((e, i) => (
                <div key={i} className="eng-row">
                  <div className="nm">{e.who}</div>
                  <div className="eng-bars">
                    <div className="eng-bar a" style={{width: e.a + "%"}}></div>
                    <div className="eng-bar b" style={{width: e.b + "%"}}></div>
                  </div>
                  <div className="v">{e.a} / {e.b}%</div>
                </div>
              ))}
            </div>
          </div>

          <div className="card chart-card">
            <h3>Opinionsledare</h3>
            <div className="sub">Vilka agenter blev informationsmäklare under simuleringen.</div>
            <div className="leaders">
              {R.leaders.map((l, i) => (
                <div className="leader-row" key={i}>
                  <div className="rank">{String(i+1).padStart(2,"0")}</div>
                  <div className="infl-meta">
                    <div className="nm">{l.name}</div>
                    <div className="sub">{l.role}</div>
                    <div className="stats">{l.desc}</div>
                  </div>
                  <div className="reach">{l.reach}<span className="u"> kontakter</span></div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Heatmap */}
        <Heatmap onPersonaJump={onPersonaJump} />

        {/* Drift */}
        <div className="card chart-card">
          <h3>Ämnesdrift över tid</h3>
          <div className="sub">Hur konversationens fokus förändrades under simuleringens 24 timmar.</div>
          <DriftChart drift={R.drift} />
          <div className="drift-legend">
            {R.drift.topics.map((t, i) => (
              <div key={i}>
                <span className="sw" style={{background: t.color}}></span>
                {t.name} <span className="muted">— slutar på {t.values[t.values.length-1]}%</span>
              </div>
            ))}
          </div>
        </div>

        {/* Notes */}
        <div className="card notes-card">
          <div className="kicker-line">Slutsatser för kampanjteamet</div>
          <ul>
            {R.notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </div>
      </div>
      )}

      <div className="export-row">
        <div className="meta">Färdig att dela med kampanjteamet — inkluderar alla diagram, persona-anteckningar och slutsatser.</div>
        <ExportButton />
      </div>

      <div className="nav-bar">
        <button className="btn btn-ghost" onClick={onRestart}>← Börja om från Steg 1</button>
        <div className="muted small">Demosimulering · uppdiktade men realistiska siffror</div>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────
   Run-overlay
   ───────────────────────────────────────────────────────────── */
const RUN_PHASES = [
  "Initierar 1 200 agenter…",
  "Tilldelar bostadsområde och yrkesprofil…",
  "Distribuerar budskap A till feeden…",
  "Distribuerar budskap B till feeden…",
  "Simulerar tidiga reaktioner (timme 0–4)…",
  "Spårar delningar och kommentarer (timme 4–12)…",
  "Mäter ämnesdrift och opinionsspridning (timme 12–24)…",
  "Sammanställer engagemang per kohort…",
  "Identifierar opinionsledare…",
  "Skriver rapport…",
] as const;

function RunOverlay({ onDone }: RunOverlayProps) {
  const [pct, setPct] = useState(0);
  const [msg, setMsg] = useState("Initierar agenter…");
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    let p = 0;
    const id = setInterval(() => {
      p += 4 + Math.random() * 5;
      if (p >= 100) {
        p = 100;
        setPct(100);
        setMsg("Klart.");
        clearInterval(id);
        setTimeout(() => onDoneRef.current(), 350);
      } else {
        setPct(p);
        setMsg(RUN_PHASES[Math.min(RUN_PHASES.length - 1, Math.floor((p / 100) * RUN_PHASES.length))]!);
      }
    }, 180);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="run-overlay">
      <div className="run-box">
        <h2>Kör simulering</h2>
        <div className="sub">1 200 agenter · 24 timmars konversation</div>
        <div className="run-progress"><div className="fill" style={{width: pct + "%"}}></div></div>
        <div className="run-status">{msg}</div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   App
   ───────────────────────────────────────────────────────────── */
export function SimulatorPage() {
  const [step, setStep] = useState(1);
  const [maxReached, setMaxReached] = useState(1);

  const [population, setPopulation] = useState("norrkoping");
  const [activePersona, setActivePersona] = useState(0);
  const [msgA, setMsgA] = useState(MSG_TEMPLATES.a[0]);
  const [msgB, setMsgB] = useState(MSG_TEMPLATES.b[0]);
  const [time, setTime] = useState("24h");
  const [news, setNews] = useState(false);
  const [newsType, setNewsType] = useState("competing");
  const [running, setRunning] = useState(false);

  const [presentation, setPresentation] = useState(false);
  const [story, setStory] = useState(false);

  function goTo(s: number) {
    setStep(s);
    setMaxReached(m => Math.max(m, s));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function next() {
    if (step === 4) {
      setRunning(true);
      return;
    }
    goTo(step + 1);
  }
  function back() { if (step > 1) goTo(step - 1); }

  function runDone() {
    setRunning(false);
    goTo(5);
  }

  function restart() {
    setStep(1);
    setMaxReached(1);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function jumpToPersona(persona: (typeof PERSONAS)[number]) {
    const i = PERSONAS.findIndex(p => p.initials === persona.initials);
    if (i >= 0) {
      setActivePersona(i);
      goTo(2);
    }
  }

  function startStory() {
    setStep(1);
    setMaxReached(5); // unlock all
    setStory(true);
  }

  function storyStep(s: number) {
    if (s === 5) {
      // ensure we're past the run gate
      setStep(5);
      setMaxReached(5);
    } else {
      setStep(s);
      setMaxReached(m => Math.max(m, s));
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const canProceed = useMemo(() => {
    if (step === 3) return msgA.trim().length > 10 && msgB.trim().length > 10;
    return true;
  }, [step, msgA, msgB]);

  const popName = POPULATIONS.find(p => p.id === population)?.name;
  const timeLabel = TIME_OPTIONS.find(o => o.id === time)?.label;

  return (
    <div className={"theme-simulator" + (presentation ? " presentation" : "")}>
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <div className="brand-mark"></div>
          <div>
            <div style={{fontFamily:"var(--font-display)", fontSize:18, color:"var(--ink)"}}>Opinionssimulator</div>
            <div className="brand-meta">Demo · Norrköping · 2026</div>
          </div>
        </div>
        <div className="tb-actions">
          <nav className="tb-sections" aria-label="Huvudmeny">
            <Link to="/personas">Personas</Link>
            <Link to="/populations">Populationer</Link>
            <Link to="/runs">Körningar</Link>
          </nav>
          <span className="tb-meta">
            {popName} · {timeLabel}{news ? " · m. störning" : ""}
          </span>
          <button
            className={"icon-btn play " + (story ? "on" : "")}
            onClick={() => story ? setStory(false) : startStory()}
            title="Auto-stegar genom alla 5 steg"
          >
            <span className="ic"></span>
            {story ? "Stoppa demo" : "Spela demo"}
          </button>
          <button
            className={"icon-btn pres " + (presentation ? "on" : "")}
            onClick={() => setPresentation(p => !p)}
            title="Större typsnitt, högre kontrast, dolda admin-element"
          >
            <span className="ic"></span>
            {presentation ? "Avsluta presentation" : "Presentationsläge"}
          </button>
        </div>
      </div>

      <Stepper step={step} maxReached={maxReached} onJump={goTo} />

      {step === 1 && <StepPopulation value={population} onChange={setPopulation} />}
      {step === 2 && <StepPersonas activeIdx={activePersona} onActiveChange={setActivePersona} />}
      {step === 3 && <StepMessages msgA={msgA} msgB={msgB} setMsgA={setMsgA} setMsgB={setMsgB} />}
      {step === 4 && <StepScenario time={time} setTime={setTime} news={news} setNews={setNews} newsType={newsType} setNewsType={setNewsType} />}
      {step === 5 && (
        <StepResults
          onRestart={restart}
          scenario={{ popName, timeLabel, news, newsType }}
          msgA={msgA}
          msgB={msgB}
          onPersonaJump={jumpToPersona}
        />
      )}

      {step < 5 && (
        <div className="nav-bar">
          <button className="btn btn-ghost" onClick={back} disabled={step === 1}>← Tillbaka</button>
          {step === 4 ? (
            <button className="btn btn-run" onClick={next} disabled={!canProceed}>
              ▶ Kör simulering
            </button>
          ) : (
            <button className="btn btn-primary btn-big" onClick={next} disabled={!canProceed}>
              Nästa: {["Personas","Budskap","Scenario","Kör"][step-1]} →
            </button>
          )}
        </div>
      )}

      <div className="app-footer">
        <span><span className="brand-mini">Opinionssimulator</span> · Demoversion för intern presentation</span>
        <span>Senast uppdaterad: april 2026</span>
      </div>

      {running && <RunOverlay onDone={runDone} />}
      {story && <StoryMode onStepChange={storyStep} onEnd={() => setStory(false)} />}
    </div>
    </div>
  );
}

