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

/** U-100 syringe (1 mL total), 29G x 1/2 in */
function Syringe({ units }: { units: number }) {
  const width = 360, height = 80;
  const padL = 24, padR = 24;
  const y = 28, h = 18;
  const x = padL, w = width - padL - padR;

  const xFor = (u: number) => x + (Math.max(0, Math.min(100, u)) / 100) * w;
  const fillW = Math.max(0, xFor(units) - x);

  const ticks: JSX.Element[] = [];
  for (let u = 0; u <= 100; u += 10) {
    const xx = xFor(u);
    ticks.push(<line key={"l"+u} x1={xx} y1={y-8} x2={xx} y2={y+h+8} stroke="#222" strokeWidth={u%50===0?2:1} />);
    ticks.push(<text key={"t"+u} x={xx} y={y+h+24} fontSize={10} textAnchor="middle" fill="#222">{u}</text>);
  }

  return (
    <svg width={width} height={height} role="img" aria-label={`Syringe showing ${units.toFixed(1)} units`}>
      <rect x={4} y={y + h/2 - 1} width={padL - 8} height={2} fill="#888" />
      <rect x={x} y={y} width={w} height={h} rx={3} ry={3} fill="#f8f8f8" stroke="#222" />
      <rect x={x} y={y} width={fillW} height={h} fill="#cde4ff" />
      <rect x={width - padR - 6} y={y - 6} width={10} height={h + 12} fill="#ddd" stroke="#222" />
      {ticks}
      <text x={width - 6} y={12} fontSize={10} textAnchor="end" fill="#333">U-100 - 29G x 1/2 in</text>
    </svg>
  );
}

export default function App() {
  const [selectedId, setSelectedId] = useState<string>(PEPTIDES[0].id);
  const selected = useMemo(() => PEPTIDES.find(p => p.id === selectedId)!, [selectedId]);

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

  const mgPerMl = useMemo(() => (waterMl > 0 ? vialMg / waterMl : 0), [vialMg, waterMl]);
  const mgPerUnit = useMemo(() => mgPerMl / 100, [mgPerMl]);
  const unitsPerDoseRaw = useMemo(() => (mgPerMl > 0 ? (doseMg / mgPerMl) * 100 : 0), [doseMg, mgPerMl]);
  const unitsPerDose = clamp(unitsPerDoseRaw, 0, 200);

  const shotsPerBottle = useMemo(() => (doseMg > 0 ? vialMg / doseMg : 0), [vialMg, doseMg]);
  const totalShots = useMemo(() => shotsPerWeek * runWeeks, [shotsPerWeek, runWeeks]);
  const bottlesNeeded = useMemo(() => (shotsPerBottle > 0 ? Math.ceil(totalShots / shotsPerBottle) : 0), [totalShots, shotsPerBottle]);

  const fullSyr = Math.floor(waterMl / 1);
  const remMl = round2(waterMl - fullSyr);

  const summary =
`Name: ${selected.name}
Amount in bottle: ${vialMg} mg
Reconstitution water: ${waterMl} mL = ${fullSyr} full syringe(s)${remMl>0?` + ${remMl} mL`:``}
Concentration: ${fmt(mgPerMl)} mg/mL
Dose: ${doseMg} mg -> draw ${fmt(unitsPerDose,1)} units (U-100)
Shots per bottle: ${fmt(shotsPerBottle,1)}
Schedule: ${shotsPerWeek} shots/week for ${runWeeks} week(s)
Rest: ${restWeeks} week(s)
Total shots: ${totalShots}
Bottles needed: ${bottlesNeeded}`;

  const inpStyle: React.CSSProperties = { width:"100%", boxSizing:"border-box", padding:"8px 10px", border:"1px solid #cbd5e1", borderRadius:8, fontSize:14 };
  const btnStyle: React.CSSProperties = { border:"1px solid #cbd5e1", background:"#fff", padding:"6px 10px", borderRadius:8, cursor:"pointer" };

  return (
    <main style={{minHeight:"100vh", padding:24, color:"#0f172a", background:"#fff"}}>
      <div style={{maxWidth:920, margin:"0 auto"}}>
        <h1 style={{margin:0, fontSize:24}}>Peptide Protocol Builder</h1>
        <p style={{marginTop:6, color:"#64748b"}}>Dropdown + syringe, bottles needed, run/rest weeks.</p>

        <section style={{border:"1px solid #e5e7eb", borderRadius:12, padding:16, marginTop:16}}>
          <div style={{display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:12}}>
            <label>
              <div style={{fontSize:12, color:"#666", marginBottom:6}}>Peptide</div>
              <select value={selectedId} onChange={e=>setSelectedId(e.target.value)} style={inpStyle}>
                {PEPTIDES.map(p=> <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <LabeledNumber label="Amount in bottle (mg)" value={vialMg} onChange={setVialMg} step={0.1} />
            <label>
              <div style={{fontSize:12, color:"#666", marginBottom:6}}>Water to add (mL)</div>
              <input type="number" value={waterMl} step={0.1} onChange={e=>setWaterMl(Number(e.target.value))} style={inpStyle}/>
              <div style={{fontSize:12, color:"#666", marginTop:6}}>= {fullSyr} full syringe(s) (1 mL each){remMl>0?` + ${remMl} mL`:""}</div>
            </label>
            <LabeledNumber label="Dose per injection (mg)" value={doseMg} onChange={setDoseMg} step={0.01} />
            <LabeledNumber label="Shots per week" value={shotsPerWeek} onChange={setShotsPerWeek} step={1} />
            <label>
              <div style={{fontSize:12, color:"#666", marginBottom:6}}>Run weeks / Rest weeks</div>
              <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:8}}>
                <input type="number" value={runWeeks} step={1} onChange={e=>setRunWeeks(Number(e.target.value))} style={inpStyle}/>
                <input type="number" value={restWeeks} step={1} onChange={e=>setRestWeeks(Number(e.target.value))} style={inpStyle}/>
              </div>
            </label>
          </div>
        </section>

        <section style={{border:"1px solid #e5e7eb", borderRadius:12, padding:16, marginTop:16}}>
          <Row k="Concentration" v={`${fmt(mgPerMl)} mg/mL`} />
          <Row k="Mg per unit (U-100)" v={`${fmt(mgPerUnit,4)} mg`} />
          <Row k="Units to draw" v={`${fmt(unitsPerDose,1)} units`} big />
          {unitsPerDoseRaw > 100 && <p style={{color:"#b00020", marginTop:6}}>Warning: dose exceeds 1 mL (100 units); use more than one syringe.</p>}
          <Syringe units={Math.min(100, Math.max(0, unitsPerDose))} />
          <p style={{ color:"#555", marginTop:-8 }}>U-100 insulin syringe (1 mL total), 29G x 1/2 in</p>
        </section>

        <section style={{border:"1px solid #e5e7eb", borderRadius:12, padding:16, marginTop:16}}>
          <Row k="Shots per bottle" v={fmt(shotsPerBottle,1)} />
          <Row k="Total shots (run)" v={String(totalShots)} />
          <Row k="Bottles needed" v={String(bottlesNeeded)} />
        </section>

        <section style={{border:"1px solid #e5e7eb", borderRadius:12, padding:16, marginTop:16}}>
          <div style={{display:"flex", justifyContent:"space-between", alignItems:"center"}}>
            <h2 style={{margin:0, fontSize:18}}>Protocol summary</h2>
            <button style={btnStyle} onClick={()=>navigator.clipboard.writeText(summary)}>Copy</button>
          </div>
          <textarea readOnly value={summary} style={{width:"100%", height:140, marginTop:8, border:"1px solid #cbd5e1", borderRadius:8, padding:10, fontFamily:"ui-monospace, Menlo, monospace", fontSize:12}}/>
        </section>
      </div>
    </main>
  );
}

function LabeledNumber({label, value, onChange, step}:{label:string; value:number; onChange:(n:number)=>void; step?:number}) {
  const style: React.CSSProperties = { width:"100%", boxSizing:"border-box", padding:"8px 10px", border:"1px solid #cbd5e1", borderRadius:8, fontSize:14 };
  return (
    <label>
      <div style={{fontSize:12, color:"#666", marginBottom:6}}>{label}</div>
      <input type="number" value={Number.isFinite(value)?value:0} step={step??1} onChange={(e)=>onChange(Number(e.target.value))} style={style}/>
    </label>
  );
}

function Row({k, v, big}:{k:string; v:string; big?:boolean}) {
  return (
    <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", padding:"6px 0", borderTop:"1px dashed #eee"}}>
      <span style={{color:"#64748b"}}>{k}</span>
      <span style={{fontWeight:big?700:600, fontSize:big?28:14}}>{v}</span>
    </div>
  );
}
