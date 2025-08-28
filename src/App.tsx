import { useMemo, useState, useEffect } from "react";

/** ---- Types & sample data (replace with your real list later) ---- */
type Peptide = {
  id: string;
  name: string;            // e.g., "Tesamorelin"
  vialMg: number;          // total mg in the vial
  defaultWaterMl: number;  // how much bac water to add (mL)
  defaultDoseMg: number;   // mg per injection (example default)
  defaultShotsPerWeek: number;
  defaultWeeks: number;       // run weeks
  defaultRestWeeks: number;   // rest weeks
};

const PEPTIDES: Peptide[] = [
  {
    id: "tesa-5",
    name: "Tesamorelin (5 mg)",
    vialMg: 5,
    defaultWaterMl: 2,
    defaultDoseMg: 0.5,
    defaultShotsPerWeek: 5,
    defaultWeeks: 12,
    defaultRestWeeks: 4,
  },
  {
    id: "slupp-10",
    name: "SLU-PP-332 (10 mg)",
    vialMg: 10,
    defaultWaterMl: 2,
    defaultDoseMg: 1,
    defaultShotsPerWeek: 5,
    defaultWeeks: 8,
    defaultRestWeeks: 4,
  },
  {
    id: "5amq-10",
    name: "5-Amino-1MQ (10 mg)",
    vialMg: 10,
    defaultWaterMl: 2,
    defaultDoseMg: 1,
    defaultShotsPerWeek: 5,
    defaultWeeks: 8,
    defaultRestWeeks: 4,
  },
];

/** ---- Main App ---- */
export default function App() {
  const [selectedId, setSelectedId] = useState<string>(PEPTIDES[0].id);

  // derived selection
  const selected = useMemo(
    () => PEPTIDES.find(p => p.id === selectedId)!,
    [selectedId]
  );

  // editable fields (preload with selected defaults)
  const [vialMg, setVialMg] = useState<number>(selected.vialMg);
  const [waterMl, setWaterMl] = useState<number>(selected.defaultWaterMl);
  const [doseMg, setDoseMg] = useState<number>(selected.defaultDoseMg);
  const [shotsPerWeek, setShotsPerWeek] = useState<number>(selected.defaultShotsPerWeek);
  const [runWeeks, setRunWeeks] = useState<number>(selected.defaultWeeks);
  const [restWeeks, setRestWeeks] = useState<number>(selected.defaultRestWeeks);

  // when dropdown changes, reset fields to that peptide's defaults
  useEffect(() => {
    setVialMg(selected.vialMg);
    setWaterMl(selected.defaultWaterMl);
    setDoseMg(selected.defaultDoseMg);
    setShotsPerWeek(selected.defaultShotsPerWeek);
    setRunWeeks(selected.defaultWeeks);
    setRestWeeks(selected.defaultRestWeeks);
  }, [selectedId]);

  /** ---- Math ---- */
  const mgPerMl = useMemo(() => (waterMl > 0 ? vialMg / waterMl : 0), [vialMg, waterMl]);
  const mgPerUnit = useMemo(() => mgPerMl / 100, [mgPerMl]);         // 1 mL = 100 units on U-100
  const unitsPerDoseRaw = useMemo(
    () => (mgPerMl > 0 ? (doseMg / mgPerMl) * 100 : 0),
    [doseMg, mgPerMl]
  );
  const unitsPerDose = clamp(unitsPerDoseRaw, 0, 200); // allow display beyond 100 with warning

  const shotsPerBottle = useMemo(
    () => (doseMg > 0 ? vialMg / doseMg : 0),
    [vialMg, doseMg]
  );
  const totalShots = useMemo(
    () => shotsPerWeek * runWeeks,
    [shotsPerWeek, runWeeks]
  );
  const bottlesNeeded = useMemo(
    () => (shotsPerBottle > 0 ? Math.ceil(totalShots / shotsPerBottle) : 0),
    [totalShots, shotsPerBottle]
  );

  // "How many full syringes of bac water"
  const fullSyringes = Math.floor(waterMl / 1);              // each U-100 is 1 mL
  const remainderMl = round2(waterMl - fullSyringes);

  // Summary text
  const summary = [
    `Name: ${selected.name}`,
    `Amount in bottle: ${vialMg} mg`,
    `Reconstitution water: ${waterMl} mL = ${fullSyringes} full syringe(s)` + (remainderMl > 0 ? ` + ${remainderMl} mL` : ""),
    `Concentration: ${fmt(mgPerMl)} mg/mL`,
    `Dose: ${doseMg} mg → draw ${fmt(unitsPerDose, 1)} units (U-100)`,
    `Shots per bottle: ${fmt(shotsPerBottle, 1)}`,
    `Schedule: ${shotsPerWeek} shots/week for ${runWeeks} week(s)`,
    `Rest: ${restWeeks} week(s)`,
    `Total shots: ${totalShots}`,
    `Bottles needed: ${bottlesNeeded}`
  ].join("\n");

  return (
    <main style={styles.page}>
      <div style={styles.wrap}>
        <h1 style={styles.h1}>Peptide Protocol Builder</h1>
        <p style={styles.sub}>Research calculator only. Not medical advice.</p>

        {/* Picker */}
        <section style={styles.card}>
          <div style={styles.grid3}>
            <Field label="Peptide">
              <select value={selectedId} onChange={e=>setSelectedId(e.target.value)} style={styles.input}>
                {PEPTIDES.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </Field>

            <Field label="Amount in bottle (mg)">
              <NumberInput value={vialMg} onChange={setVialMg} step={0.1} />
            </Field>

            <Field label="Water to add (mL)">
              <NumberInput value={waterMl} onChange={setWaterMl} step={0.1} />
              <small style={styles.note}>
                = {fullSyringes} full syringe(s) (1 mL each){remainderMl > 0 ? ` + ${remainderMl} mL` : ""}
              </small>
            </Field>

            <Field label="Dose per injection (mg)">
              <NumberInput value={doseMg} onChange={setDoseMg} step={0.01} />
            </Field>

            <Field label="Shots per week">
              <NumberInput value={shotsPerWeek} onChange={setShotsPerWeek} step={1} />
            </Field>

            <Field label="Run weeks / Rest weeks">
              <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:8}}>
                <NumberInput value={runWeeks} onChange={setRunWeeks} step={1} />
                <NumberInput value={restWeeks} onChange={setRestWeeks} step={1} />
              </div>
            </Field>
          </div>
        </section>

        {/* Dose + syringe visual */}
        <section style={styles.card}>
          <div style={{display:"grid", gap:16}}>
            <div>
              <div style={styles.row}>
                <span style={styles.k}>Concentration</span>
                <span style={styles.v}>{fmt(mgPerMl)} mg/mL</span>
              </div>
              <div style={styles.row}>
                <span style={styles.k}>Mg per unit (U-100)</span>
                <span style={styles.v}>{fmt(mgPerUnit,4)} mg</span>
              </div>
              <div style={styles.row}>
                <span style={styles.k}>Units to draw</span>
                <span style={styles.big}>{fmt(unitsPerDose,1)} units</span>
              </div>
              {unitsPerDoseRaw > 100 && (
                <p style={{color:"#b00020", marginTop:6}}>
                  ⚠️ Dose exceeds 1 mL (100 units). You’d need more than one syringe.
                </p>
              )}
            </div>

            <Syringe units={Math.min(100, Math.max(0, unitsPerDose))} />
            <p style={{color:"#555", marginTop:-8}}>U-100 insulin syringe (1 mL total), 29G × ½″</p>
          </div>
        </section>

        {/* Totals */}
        <section style={styles.card}>
          <div style={styles.row}>
            <span style={styles.k}>Shots per bottle</span>
            <span style={styles.v}>{fmt(shotsPerBottle,1)}</span>
          </div>
          <div style={styles.row}>
            <span style={styles.k}>Total shots (run)</span>
            <span style={styles.v}>{totalShots}</span>
          </div>
          <div style={styles.row}>
            <span style={styles.k}>Bottles needed</span>
            <span style={styles.v}>{bottlesNeeded}</span>
          </div>
        </section>

        {/* Summary box */}
        <section style={styles.card}>
          <div style={{display:"flex", justifyContent:"space-between", alignItems:"center"}}>
            <h2 style={{margin:0, fontSize:18}}>Protocol summary</h2>
            <button style={styles.button} onClick={()=>copy(summary)}>Copy</button>
          </div>
          <textarea readOnly value={summary} style={styles.textarea} />
        </section>

        <p style={{fontSize:12, color:"#777"}}>
          Notes: 1 mL = 100 units on a U-100 syringe. This tool is for research/info only.
        </p>
      </div>
    </main>
  );
}

/** ---- Components ---- */
function Field(props: {label: string; children: React.ReactNode}) {
  return (
    <label style={{display:"block"}}>
      <div style={{fontSize:12, color:"#666", marginBottom:6}}>{props.label}</div>
      {props.children}
    </label>
  );
}
function NumberInput(props:{value:number; onChange:(n:number)=>void; step?:number}) {
  return (
    <input
      type="number"
      value={Number.isFinite(props.value) ? props.value : 0}
      step={props.step ?? 1}
      onChange={e=>props.onChange(Number(e.target.value))}
      style={styles.input}
    />
  );
}

/** Syringe SVG: 1 mL total with 0–100 unit ticks */
function Syringe({units}:{units:number}) {
  const width = 360;
  const height = 70;
  const leftPad = 20;
  const rightPad = 20;
  const barrelY = 30;
  const barrelH = 16;
  const barrelX = leftPad;
  const barrelW = width - leftPad - rightPad;

  const xForUnits = (u:number) => barrelX + (Math.max(0, Math.min(100, u)) / 100) * barrelW;

  const ticks: JSX.Element[] = [];
  for (let u = 0; u <= 100; u += 10) {
    const x = xForUnits(u);
    ticks.push(<line key={u} x1={x} y1={barrelY-8} x2={x} y2={barrelY+barrelH+8} stroke="#222" strokeWidth={u % 50 === 0 ? 2 : 1}/>);
    // label every 10
    ticks.push(<text key={`t${u}`} x={x} y={barrelY+barrelH+24} fontSize={10} textAnchor="middle" fill="#222">{u}</text>);
  }

  return (
    <svg width={width} height={height} role="img" aria-label={`Syringe showing ${units.toFixed(1)} units`}>
      {/* Needle + hub (simple) */}
      <rect x={2} y={barrelY+barrelH/2-1} width={leftPad-4} height={2} fill="#888" />
      {/* Barrel */}
      <rect x={barrelX} y={barrelY} width={barrelW} height={barrelH} rx={3} ry={3} fill="#f8f8f8} stroke="#222" />
      {/* Fill to units */}
      <rect x={barrelX} y={barrelY} width={xForUnits(units)-barrelX} height={barrelH} fill="#cde4ff" />
      {/* Plunger cap */}
      <rect x={width-rightPad} y={barrelY-6} width={8} height={barrelH+12} fill="#ddd" stroke="#222" />
      {/* Ticks + labels */}
      {ticks}
      {/* Text */}
      <text x={width-4} y={12} fontSize={10} textAnchor="end" fill="#333">U-100 • 29G × ½″</text>
    </svg>
  );
}

/** ---- utils & styles ---- */
function fmt(n:number, d=3){ return Number.isFinite(n) ? n.toFixed(d) : "0"; }
function round2(n:number){ return Math.round(n*100)/100; }
function clamp(n:number, a:number, b:number){ return Math.min(b, Math.max(a, n)); }

const styles: Record<string, React.CSSProperties> = {
  page: { minHeight: "100vh", background:"#fff", color:"#0f172a", padding:"24px" },
  wrap: { maxWidth: 880, margin:"0 auto" },
  h1: { fontSize: 24, margin: 0 },
  sub: { color:"#64748b", margin:"6px 0 16px" },
  grid3: { display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:12 },
  card: { border:"1px solid #e5e7eb", borderRadius:12, padding:16, marginTop:16 },
  row: { display:"flex", justifyContent:"space-between", alignItems:"center", padding:"6px 0", borderTop:"1px dashed #eee" },
  k: { color:"#64748b" },
  v: { fontWeight: 600 },
  big: { fontWeight: 700, fontSize: 28 },
  input: { width:"100%", boxSizing:"border-box", padding:"8px 10px", border:"1px solid #cbd5e1", borderRadius:8, fontSize:14 },
  button: { border:"1px solid #cbd5e1", background:"#fff", padding:"6px 10px", borderRadius:8, cursor:"pointer" },
  textarea: { width:"100%", height:140, marginTop:8, border:"1px solid #cbd5e1", borderRadius:8, padding:10, fontFamily:"ui-monospace, Menlo, monospace", fontSize:12 },
};
