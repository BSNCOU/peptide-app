import React, { useEffect, useMemo, useState } from "react";

type Peptide = {
  id: string;
  name: string;
  vialMg: number;
  defaultWaterMl: number;
  defaultDoseMg: number;
  defaultShotsPerWeek: number;
  defaultRunWeeks: number;
  defaultRestWeeks: number;
};

const PEPTIDES: Peptide[] = [
  { id: "tesa-5",   name: "Tesamorelin (5 mg)", vialMg: 5,  defaultWaterMl: 2, defaultDoseMg: 0.5, defaultShotsPerWeek: 5, defaultRunWeeks: 12, defaultRestWeeks: 4 },
  { id: "slupp-10", name: "SLU-PP-332 (10 mg)", vialMg: 10, defaultWaterMl: 2, defaultDoseMg: 1.0, defaultShotsPerWeek: 5, defaultRunWeeks: 8,  defaultRestWeeks: 4 },
  { id: "5amq-10",  name: "5-Amino-1MQ (10 mg)", vialMg: 10, defaultWaterMl: 2, defaultDoseMg: 1.0, defaultShotsPerWeek: 5, defaultRunWeeks: 8,  defaultRestWeeks: 4 },
];

const fmt = (n: number, d = 3) => (Number.isFinite(n) ? n.toFixed(d) : "0");
const round2 = (n: number) => Math.round(n * 100) / 100;
const clamp = (n: number, a: number, b: number) => Math.min(b, Math.max(a, n));

async function copyToClipboard(text: string) {
  try { await navigator.clipboard.writeText(text); alert("Copied!"); }
  catch { alert("Could not copy. Select and copy manually."); }
}

/** U-100 syringe (1 mL total), 29G x 1/2 in */
function Syringe({ units }: { units: number }) {
  const width = 360, height = 80;
  const leftPad = 24, rightPad = 24;
  const barrelY = 28, barrelH = 18;
  const barrelX = leftPad, barrelW = width - leftPad - rightPad;

  const xForUnits = (u: number) => barrelX + (Math.max(0, Math.min(100, u)) / 100) * barrelW;

  const ticks: JSX.Element[] = [];
  for (let u = 0; u <= 100; u += 10) {
    const x = xForUnits(u);
    ticks.push(<line key={`l${u}`} x1={x} y1={barrelY-8} x2={x} y2={barrelY+barrelH+8} stroke="#222" strokeWidth={u%50===0?2:1} />);
    ticks.push(<text key={`t${u}`} x={x} y={barrelY+barrelH+24} fontSize={10} textAnchor="middle" fill="#222">{u}</text>);
  }

  const fillW = Math.max(0, xForUnits(units) - barrelX);

  return (
    <svg width={width} height={height} role="img" aria-label={`Syringe showing ${units.toFixed(1)} units`}>
      {/* Needle */}
      <rect x={4} y={barrelY + barrelH/2 - 1} width={leftPad - 8} height={2} fill="#888" />
      {/* Barrel */}
      <rect x={barrelX} y={barrelY} width={barrelW} height={barrelH} rx={3} ry={3} fill="#f8f8f8" stroke="#222" />
      {/* Fill */}
      <rect x={barrelX} y={barrelY} width={fillW} height={barrelH} fill="#cde4ff" />
      {/* Plunger cap */}
      <rect x={width - rightPad - 6} y={barrelY - 6} width={10} height={barrelH + 12} fill="#ddd" stroke="#222" />
      {/* Ticks + labels */}
      {ticks}
      <text x={width - 6} y={12} fontSize={10} textAnchor="end" fill="#333">U-100 - 29G x 1/2 in</text>
    </svg>
  );
}

export default function App() {
  const [selectedId, setSelectedId] = useState<string>(PEPTIDES[0].id);
  const selected = useMemo(() => PEPTIDES.find(p => p.id === selectedId)!, [selectedId]);

  // fields seeded by selection
  const [vialMg, setVialMg] = useState<number>(selected.vialMg);
  const [waterMl, setWaterMl] = useState<number>(selected.defaultWaterMl);
  const [doseMg, setDoseMg] = useState<number>(selected.defaultDoseMg);
  const [shotsPerWeek, setShotsPerWeek] = useState<number>(selected.defaultShotsPerWeek);
  const [runWeeks, setRunWeeks] = useState<number>(selected.defaultRunWeeks);
  const [restWeeks, setRestWeeks] = useState<number>(selected.defaultRestWeeks);

  useEffect(() => {
    setVialMg(selected.vialMg);
    setWaterMl(selected.defaultWaterMl);
    setDoseMg(selected.defaultDoseMg);
    setShotsPerWeek(selected.defaultShotsPerWeek);
    setRunWeeks(selected.defaultRunWeeks);
    setRestWeeks(selected.defaultRestWeeks);
  }, [selectedId]);

  // math
  const mgPerMl = useMemo(() => (waterMl > 0 ? vialMg / waterMl : 0), [vialMg, waterMl]);
  const mgPerUnit = useMemo(() => mgPerMl / 100, [mgPerMl]); // 1 mL = 100 units
  const unitsPerDoseRaw = useMemo(() => (mgPerMl > 0 ? (doseMg / mgPerMl) * 100 : 0), [doseMg, mgPerMl]);
  const unitsPerDose = clamp(unitsPerDoseRaw, 0, 200);

  const shotsPerBottle = useMemo(() => (doseMg > 0 ? vialMg / doseMg : 0), [vialMg, doseMg]);
  const totalShots     = useMemo(() => shotsPerWeek * runWeeks, [shotsPerWeek, runWeeks]);
  const bottlesNeeded  = useMemo(() => (shotsPerBottle > 0 ? Math.ceil(totalShots / shotsPerBottle) : 0), [totalShots, shotsPerBottle]);

  const fullSyringes = Math.floor(waterMl / 1);
  const remainderMl  = round2(waterMl - fullSyringes);

  const summary =
`Name: ${selected.name}
Amount in bottle: ${vialMg} mg
Reconstitution water: ${waterMl} mL = ${fullSyringes} full syringe(s)${remainderMl>0?` + ${remainderMl} mL`:``}
Concentration: ${fmt(mgPerMl)} mg/mL
Dose: ${doseMg} mg -> draw ${fmt(unitsPerDose,1)} units (U-100)
Shots per bottle: ${fmt(shotsPerBottle,1)}
Schedule: ${shotsPerWeek} shots/week for ${runWeeks} week(s)
Rest: ${restWeeks} week(s)
Total shots: ${totalShots}
Bottles needed: ${bottlesNeeded}`;

  return (
    <main style={{ minHeight:"100vh", background:"#fff", color:"#0f172a", padding:24 }}>
      <div style={{ maxWidth:920, margin:"0 auto" }}>
        <h1 style={{ margin:0, fontSize:24 }}>Peptide Protocol Builder</h1>
        <p style={{ marginTop:6, color:"#64748b" }}>Pick a peptide; get units to draw, shots/bottle, bottles needed, and run/rest weeks.</p>

        <section style={card}>
          <div style={grid3}>
            <Field label="Peptide">
              <select value={selectedId} onChange={(e)=>setSelectedId(e.target.value)} style={input}>
                {PEPTIDES.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </Field>
            <Field label="Amount in bottle (mg)"><Num value={vialMg} onChange={setVialMg} step={0.1}/></Field>
            <Field label="Water to add (mL)">
              <Num value={waterMl} onChange={setWaterMl} step={0.1}/>
              <div style={{ fontSize:12, color:"#666", marginTop:6 }}>
                = {fullSyringes} full syringe(s) (1 mL each){remainderMl>0?` + ${remainderMl} mL`:``}
              </div>
            </Field>
            <Field label="Dose per injection (mg)"><Num value={doseMg} onChange={setDoseMg} step={0.01}/></Field>
            <Field label="Shots per week"><Num value={shotsPerWeek} onChange={setShotsPerWeek} step={1}/></Field>
            <Field label="Run weeks / Rest weeks">
              <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:8 }}>
                <Num value={runWeeks} onChange={setRunWeeks} step={1}/>
                <Num value={restWeeks} onChange={setRestWeeks} step={1}/>
              </div>
            </Field>
          </div>
        </section>

        <section style={card}>
          <Row k="Concentration" v={`${fmt(mgPerMl)} mg/mL`} />
          <Row k="Mg per unit (U-100)" v={`${fmt(mgPerUnit,4)} mg`} />
          <div style={row}><span style={kStyle}>Units to draw</span><span style={{ fontWeight:700, fontSize:28 }}>{fmt(unitsPerDose,1)} units</span></div>
          {unitsPerDoseRaw > 100 && <p style={{ color:"#b00020", marginTop:6 }}>Warning: dose exceeds 1 mL (100 units); use more than one syringe.</p>}
          <Syringe units={Math.min(100, Math.max(0, unitsPerDose))} />
          <p style={{ color:"#555", marginTop:-8 }}>U-100 insulin syringe (1 mL total), 29G x 1/2 in</p>
        </section>

        <section style={card}>
          <Row k="Shots per bottle" v={fmt(shotsPerBottle,1)} />
          <Row k="Total shots (run)" v={String(totalShots)} />
          <Row k="Bottles needed" v={String(bottlesNeeded)} />
        </section>

        <section style={card}>
          <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
            <h2 style={{ margin:0, fontSize:18 }}>Protocol summary</h2>
            <button style={button} onClick={()=>copyToClipboard(summary)}>Copy</button>
          </div>
          <textarea readOnly value={summary} style={textarea}/>
        </section>
      </div>
    </main>
  );
}

function Field(props: { label: string; children: React.ReactNode }) {
  return <label style={{ display:"block" }}><div style={{ fontSize:12, color:"#666", marginBottom:6 }}>{props.label}</div>{props.children}</label>;
}
function Num(props: { value: number; onChange: (n:number)=>void; step?:number }) {
  return <input type="number" value={Number.isFinite(props.value)?props.value:0} step={props.step??1} onChange={(e)=>props.onChange(Number(e.target.value))} style={input}/>;
}
function Row({k, v}:{k:string; v:string}) {
  return <div style={row}><span style={kStyle}>{k}</span><span style={{ fontWeight:600 }}>{v}</span></div>;
}

const card     = { border:"1px solid #e5e7eb", borderRadius:12, padding:16, marginTop:16 };
const grid3    = { display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:12 } as React.CSSProperties;
const input    = { width:"100%", boxSizing:"border-box", padding:"8px 10px", border:"1px solid #cbd5e1", borderRadius:8, fontSize:14 } as React.CSSProperties;
const row      = { display:"flex", justifyContent:"space-between", alignItems:"center", padding:"6px 0", borderTop:"1px dashed #eee" } as React.CSSProperties;
const kStyle   = { color:"#64748b" } as React.CSSProperties;
const button   = { border:"1px solid #cbd5e1", background:"#fff", padding:"6px 10px", borderRadius:8, cursor:"pointer" } as React.CSSProperties;
const textarea = { width:"100%", height:140, mar
