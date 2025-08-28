import { useMemo, useState } from "react";

export default function App() {
  // basic inputs
  const [peptide, setPeptide] = useState("Tesamorelin");
  const [bottleMg, setBottleMg] = useState<number>(5);    // total mg in vial
  const [waterMl, setWaterMl]   = useState<number>(2);    // mL of bacteriostatic water you add
  const [doseMg, setDoseMg]     = useState<number>(0.5);  // mg per injection
  const [shotsPerWeek, setShotsPerWeek] = useState<number>(5);
  const [weeks, setWeeks] = useState<number>(12);

  // math
  const mgPerMl     = useMemo(() => (waterMl > 0 ? bottleMg / waterMl : 0), [bottleMg, waterMl]);
  const mgPerUnit   = useMemo(() => mgPerMl / 100, [mgPerMl]);                // U-100 syringe = 100 units per mL
  const unitsPerDose = useMemo(() => (mgPerUnit > 0 ? doseMg / mgPerUnit : 0), [doseMg, mgPerUnit]);
  const shotsPerBottle = useMemo(() => (doseMg > 0 ? bottleMg / doseMg : 0), [bottleMg, doseMg]);
  const totalShots  = useMemo(() => shotsPerWeek * weeks, [shotsPerWeek, weeks]);
  const bottlesNeeded = useMemo(
    () => (shotsPerBottle > 0 ? Math.ceil(totalShots / shotsPerBottle) : 0),
    [totalShots, shotsPerBottle]
  );

  const summary = [
    `Peptide: ${peptide}`,
    `Bottle: ${bottleMg} mg`,
    `Water: ${waterMl} mL`,
    `Concentration: ${fmt(mgPerMl)} mg/mL`,
    `Dose: ${doseMg} mg → draw ${fmt(unitsPerDose, 1)} units on a U-100 syringe`,
    `Shots per bottle: ${fmt(shotsPerBottle, 1)}`,
    `Schedule: ${shotsPerWeek} shots/week × ${weeks} weeks = ${totalShots} shots`,
    `Bottles needed: ${bottlesNeeded}`,
  ].join("\n");

  async function copySummary() {
    try {
      await navigator.clipboard.writeText(summary);
      alert("Protocol summary copied!");
    } catch {
      alert("Could not copy. You can select and copy it manually.");
    }
  }

  return (
    <main className="min-h-screen bg-white text-slate-900 p-6 sm:p-10">
      <div className="max-w-3xl mx-auto space-y-6">
        <header>
          <h1 className="text-2xl sm:text-3xl font-semibold">Peptide Protocol Builder</h1>
          <p className="text-slate-600 mt-1">Enter vial amount, water, and dose. I’ll tell you the syringe units, shots per bottle, and bottles needed.</p>
        </header>

        {/* Inputs */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <Field label="Peptide name">
            <input className="input" value={peptide} onChange={(e)=>setPeptide(e.target.value)} />
          </Field>

          <Field label="Bottle (mg)">
            <NumberInput value={bottleMg} onChange={setBottleMg} step={0.1}/>
          </Field>

          <Field label="Water to add (mL)">
            <NumberInput value={waterMl} onChange={setWaterMl} step={0.1}/>
          </Field>

          <Field label="Dose per shot (mg)">
            <NumberInput value={doseMg} onChange={setDoseMg} step={0.01}/>
          </Field>

          <Field label="Shots per week">
            <NumberInput value={shotsPerWeek} onChange={setShotsPerWeek} step={1}/>
          </Field>

          <Field label="Duration (weeks)">
            <NumberInput value={weeks} onChange={setWeeks} step={1}/>
          </Field>
        </section>

        {/* Big callout */}
        <section className="rounded-2xl border border-slate-200 p-5">
          <div className="grid sm:grid-cols-2 gap-4 items-center">
            <div>
              <p className="text-sm text-slate-500">Pull to</p>
              <p className="text-4xl font-bold">{fmt(unitsPerDose, 1)} units</p>
              <p className="text-sm text-slate-500 mt-1">on a U-100 insulin syringe</p>
            </div>
            <div className="space-y-1">
              <Line label="Concentration" value={`${fmt(mgPerMl)} mg/mL`} />
              <Line label="Mg per unit" value={`${fmt(mgPerUnit, 4)} mg`} />
              <Line label="Shots per bottle" value={fmt(shotsPerBottle, 1)} />
              <Line label="Total shots" value={`${totalShots}`} />
              <Line label="Bottles needed" value={`${bottlesNeeded}`} />
            </div>
          </div>
        </section>

        {/* Summary box */}
        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="font-medium">Protocol summary</h2>
            <button onClick={copySummary} className="rounded-xl border px-3 py-1.5 text-sm hover:bg-slate-50">
              Copy
            </button>
          </div>
          <textarea readOnly value={summary} className="w-full h-40 border rounded-xl p-3 font-mono text-sm"/>
          <p className="text-xs text-slate-500">Note: 1 mL = 100 units on a U-100 syringe.</p>
        </section>
      </div>
    </main>
  );
}

/* ---------- small helpers ---------- */
function fmt(n: number, digits = 3) {
  if (!isFinite(n)) return "0";
  return n.toFixed(digits);
}

function Field(props: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-sm text-slate-600 mb-1">{props.label}</span>
      {props.children}
    </label>
  );
}

function NumberInput(props: { value: number; onChange: (v:number)=>void; step?: number }) {
  return (
    <input
      type="number"
      step={props.step ?? 1}
      value={Number.isFinite(props.value) ? props.value : 0}
      onChange={(e)=>props.onChange(Number(e.target.value))}
      className="input"
    />
  );
}

function Line(props:{label:string; value:string}) {
  return (
    <p className="flex items-center justify-between text-sm">
      <span className="text-slate-500">{props.label}</span>
      <span className="font-medium">{props.value}</span>
    </p>
  );
}

/* Tailwindy input style */
declare global {
  namespace JSX { interface IntrinsicElements { } }
}
