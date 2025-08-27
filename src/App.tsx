import React, { useMemo, useState } from "react";

type Peptide = {
  key: string;
  name: string;
  vialMg: number; // total peptide per vial (mg)
  defaultWaterMl: number; // suggested reconstitution volume (mL)
  defaultDoseMg: number; // per-injection dose (mg)
  defaultFreqPerWeek: number; // injections per week
  defaultWeeksOn: number;
  defaultWeeksOff: number;
};

const PRESETS: Peptide[] = [
  {
    key: "bpc157",
    name: "BPC-157 5mg",
    vialMg: 5,
    defaultWaterMl: 2, // 2 mL → 10 units = 0.25 mg = 250 mcg
    defaultDoseMg: 0.25,
    defaultFreqPerWeek: 7,
    defaultWeeksOn: 3,
    defaultWeeksOff: 1,
  },
  {
    key: "tesa",
    name: "Tesamorelin 5mg",
    vialMg: 5,
    defaultWaterMl: 1, // 1 mL → 20 units = 1 mg
    defaultDoseMg: 1,
    defaultFreqPerWeek: 5,
    defaultWeeksOn: 12,
    defaultWeeksOff: 4,
  },
  {
    key: "motsc",
    name: "MOTS-C 10mg",
    vialMg: 10,
    defaultWaterMl: 1, // 1 mL → 10 units = 1 mg
    defaultDoseMg: 1,
    defaultFreqPerWeek: 5,
    defaultWeeksOn: 12,
    defaultWeeksOff: 4,
  },
];

function num(v: any, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function ceil(n: number) {
  return Math.ceil(n);
}

function SyringeVisual({ units }: { units: number }) {
  const pct = Math.max(0, Math.min(100, (units / 100) * 100));
  return (
    <div className="flex items-end gap-4">
      <div className="relative h-64 w-10 rounded-xl border border-gray-300 bg-white overflow-hidden">
        <div
          className="absolute bottom-0 left-0 right-0 bg-gray-800/20"
          style={{ height: `${pct}%` }}
        />
        {[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100].map((t) => (
          <div key={t} className="absolute left-0 right-0" style={{ bottom: `${t}%` }}>
            <div className="h-px bg-gray-300" />
          </div>
        ))}
      </div>
      <div className="flex flex-col text-sm text-gray-600">
        <div className="font-medium text-gray-900">U-100 insulin syringe</div>
        <div>Mark shows where to pull plunger.</div>
        <div className="mt-2">Dose: <span className="font-semibold">{units.toFixed(1)} units</span></div>
        {units > 100 && (
          <div className="mt-1 text-red-600">Warning: dose exceeds 1.0 mL (100 units)</div>
        )}
      </div>
    </div>
  );
}

function SinglePeptideCard() {
  const [presetKey, setPresetKey] = useState(PRESETS[0].key);
  const p = PRESETS.find((x) => x.key === presetKey)!;

  const [name, setName] = useState(p.name);
  const [vialMg, setVialMg] = useState(p.vialMg);
  const [waterMl, setWaterMl] = useState(p.defaultWaterMl);
  const [doseMg, setDoseMg] = useState(p.defaultDoseMg);
  const [freq, setFreq] = useState(p.defaultFreqPerWeek);
  const [weeksOn, setWeeksOn] = useState(p.defaultWeeksOn);
  const [weeksOff, setWeeksOff] = useState(p.defaultWeeksOff);

  React.useEffect(() => {
    const next = PRESETS.find((x) => x.key === presetKey)!;
    setName(next.name);
    setVialMg(next.vialMg);
    setWaterMl(next.defaultWaterMl);
    setDoseMg(next.defaultDoseMg);
    setFreq(next.defaultFreqPerWeek);
    setWeeksOn(next.defaultWeeksOn);
    setWeeksOff(next.defaultWeeksOff);
  }, [presetKey]);

  const calc = React.useMemo(() => {
    const _vialMg = num(vialMg, 1);
    const _waterMl = Math.max(0.01, num(waterMl, 1));
    const _doseMg = Math.max(0.001, num(doseMg, 0.25));
    const _freq = Math.max(0, num(freq, 0));
    const _weeksOn = Math.max(0, num(weeksOn, 0));

    const mgPerMl = _vialMg / _waterMl;
    const unitsPerMg = 100 / mgPerMl;
    const unitsPerDose = _doseMg * unitsPerMg;

    const dosesPerVial = _vialMg / _doseMg;
    const totalDosesRequired = _freq * _weeksOn;
    const bottlesNeeded = totalDosesRequired === 0 ? 0 : ceil(totalDosesRequired / dosesPerVial);

    return {
      mgPerMl,
      unitsPerMg,
      unitsPerDose,
      dosesPerVial,
      totalDosesRequired,
      bottlesNeeded,
      weeksOff: Math.max(0, num(weeksOff, 0)),
    };
  }, [vialMg, waterMl, doseMg, freq, weeksOn, weeksOff]);

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <div className="space-y-4">
        <div className="grid gap-2">
          <label className="text-sm font-medium">Preset</label>
          <select
            className="rounded-xl border p-3"
            value={presetKey}
            onChange={(e) => setPresetKey(e.target.value)}
          >
            {PRESETS.map((pp) => (
              <option key={pp.key} value={pp.key}>
                {pp.name}
              </option>
            ))}
            <option value="custom">Custom…</option>
          </select>
        </div>

        <div className="grid gap-2">
          <label className="text-sm font-medium">Peptide name</label>
          <input className="rounded-xl border p-3" value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="grid gap-2">
            <label className="text-sm font-medium">Vial amount (mg)</label>
            <input type="number" step="0.1" className="rounded-xl border p-3" value={vialMg} onChange={(e) => setVialMg(Number(e.target.value))} />
          </div>
          <div className="grid gap-2">
            <label className="text-sm font-medium">Water to mix (mL)</label>
            <input type="number" step="0.1" className="rounded-xl border p-3" value={waterMl} onChange={(e) => setWaterMl(Number(e.target.value))} />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div className="grid gap-2">
            <label className="text-sm font-medium">Dose (mg)</label>
            <input type="number" step="0.01" className="rounded-xl border p-3" value={doseMg} onChange={(e) => setDoseMg(Number(e.target.value))} />
          </div>
          <div className="grid gap-2">
            <label className="text-sm font-medium">Times / week</label>
            <input type="number" className="rounded-xl border p-3" value={freq} onChange={(e) => setFreq(Number(e.target.value))} />
          </div>
          <div className="grid gap-2">
            <label className="text-sm font-medium">Weeks ON</label>
            <input type="number" className="rounded-xl border p-3" value={weeksOn} onChange={(e) => setWeeksOn(Number(e.target.value))} />
          </div>
        </div>

        <div className="grid gap-2">
          <label className="text-sm font-medium">Weeks OFF (rest)</label>
          <input type="number" className="rounded-xl border p-3" value={weeksOff} onChange={(e) => setWeeksOff(Number(e.target.value))} />
        </div>
      </div>

      <div className="space-y-4">
        <div className="rounded-2xl border p-4 shadow-sm bg-white">
          <div className="text-lg font-semibold">Results</div>
          <div className="mt-3 grid gap-2 text-sm">
            <div className="flex justify-between"><span>Concentration</span><span className="font-medium">{calc.mgPerMl.toFixed(3)} mg/mL</span></div>
            <div className="flex justify-between"><span>Units per mg (U-100)</span><span className="font-medium">{calc.unitsPerMg.toFixed(1)} units</span></div>
            <div className="flex justify-between"><span>Units per dose</span><span className="font-medium">{calc.unitsPerDose.toFixed(1)} units</span></div>
            <div className="flex justify-between"><span>Doses per vial</span><span className="font-medium">{calc.dosesPerVial.toFixed(1)}</span></div>
            <div className="flex justify-between"><span>Total injections this cycle</span><span className="font-medium">{calc.totalDosesRequired}</span></div>
            <div className="flex justify-between"><span>Bottles needed</span><span className="font-medium">{calc.bottlesNeeded}</span></div>
          </div>
          <div className="mt-4">
            <SyringeVisual units={calc.unitsPerDose} />
          </div>
        </div>

        <div className="rounded-2xl border p-4 text-sm bg-gray-50">
          <div className="font-semibold">Protocol Summary</div>
          <ul className="mt-2 list-disc pl-5 space-y-1">
            <li>Mix <span className="font-medium">{waterMl} mL</span> bacteriostatic water into a <span className="font-medium">{vialMg} mg</span> vial.</li>
            <li>Inject <span className="font-medium">{doseMg} mg</span> (<span className="font-medium">{calc.unitsPerDose.toFixed(1)} units</span> on a U‑100 syringe), <span className="font-medium">{freq}×/week</span>.</li>
            <li>Duration: <span className="font-medium">{weeksOn} weeks on</span>, then <span className="font-medium">{calc.weeksOff} weeks off</span>.</li>
            <li>Approx. <span className="font-medium">{calc.dosesPerVial.toFixed(1)}</span> shots per bottle → <span className="font-medium">{calc.bottlesNeeded}</span> bottles for this cycle.</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

function StackRow({ idx, data, onChange, onRemove }: any) {
  const c = useMemo(() => {
    const mgPerMl = data.vialMg / Math.max(0.01, data.waterMl);
    const unitsPerMg = 100 / mgPerMl;
    const unitsPerDose = data.doseMg * unitsPerMg;
    const dosesPerVial = data.vialMg / Math.max(0.001, data.doseMg);
    const totalDosesRequired = data.freq * data.weeksOn;
    const bottlesNeeded = totalDosesRequired === 0 ? 0 : Math.ceil(totalDosesRequired / dosesPerVial);
    return { mgPerMl, unitsPerMg, unitsPerDose, dosesPerVial, totalDosesRequired, bottlesNeeded };
  }, [data]);

  return (
    <div className="rounded-2xl border p-4 bg-white shadow-sm">
      <div className="flex items-center justify-between">
        <div className="font-semibold">{data.name || `Peptide ${idx + 1}`}</div>
        <button className="text-red-600 text-sm" onClick={onRemove}>Remove</button>
      </div>
      <div className="mt-3 grid grid-cols-2 md:grid-cols-6 gap-3 text-sm">
        <input className="rounded-xl border p-2 md:col-span-2" placeholder="Name" value={data.name} onChange={(e)=>onChange({ ...data, name: e.target.value })} />
        <input type="number" step="0.1" className="rounded-xl border p-2" placeholder="Vial mg" value={data.vialMg} onChange={(e)=>onChange({ ...data, vialMg: Number(e.target.value) })} />
        <input type="number" step="0.1" className="rounded-xl border p-2" placeholder="Water mL" value={data.waterMl} onChange={(e)=>onChange({ ...data, waterMl: Number(e.target.value) })} />
        <input type="number" step="0.01" className="rounded-xl border p-2" placeholder="Dose mg" value={data.doseMg} onChange={(e)=>onChange({ ...data, doseMg: Number(e.target.value) })} />
        <input type="number" className="rounded-xl border p-2" placeholder="/wk" value={data.freq} onChange={(e)=>onChange({ ...data, freq: Number(e.target.value) })} />
        <input type="number" className="rounded-xl border p-2" placeholder="Weeks on" value={data.weeksOn} onChange={(e)=>onChange({ ...data, weeksOn: Number(e.target.value) })} />
      </div>
      <div className="mt-3 grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
        <div className="rounded-xl border p-3 bg-gray-50">Conc: <span className="font-medium">{c.mgPerMl.toFixed(3)} mg/mL</span></div>
        <div className="rounded-xl border p-3 bg-gray-50">Units/mg: <span className="font-medium">{c.unitsPerMg.toFixed(1)}</span></div>
        <div className="rounded-xl border p-3 bg-gray-50">Units/dose: <span className="font-medium">{c.unitsPerDose.toFixed(1)}</span></div>
        <div className="rounded-xl border p-3 bg-gray-50">Shots/vial: <span className="font-medium">{c.dosesPerVial.toFixed(1)}</span></div>
        <div className="rounded-xl border p-3 bg-gray-50">Bottles: <span className="font-medium">{c.bottlesNeeded}</span></div>
      </div>
    </div>
  );
}

function StackBuilder() {
  const [rows, setRows] = useState(
    PRESETS.map((p) => ({
      name: p.name,
      vialMg: p.vialMg,
      waterMl: p.defaultWaterMl,
      doseMg: p.defaultDoseMg,
      freq: p.defaultFreqPerWeek,
      weeksOn: p.defaultWeeksOn,
    }))
  );

  const summary = useMemo(() => {
    return rows.map((r) => {
      const mgPerMl = r.vialMg / Math.max(0.01, r.waterMl);
      const unitsPerMg = 100 / mgPerMl;
      const unitsPerDose = r.doseMg * unitsPerMg;
      const dosesPerVial = r.vialMg / Math.max(0.001, r.doseMg);
      const totalDosesRequired = r.freq * r.weeksOn;
      const bottlesNeeded = totalDosesRequired === 0 ? 0 : Math.ceil(totalDosesRequired / dosesPerVial);
      return { name: r.name, unitsPerDose, dosesPerVial, bottlesNeeded };
    });
  }, [rows]);

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="text-lg font-semibold">Your Stack</div>
        <button
          className="rounded-xl bg-gray-900 text-white px-4 py-2 shadow"
          onClick={() => setRows([
            ...rows,
            { name: "", vialMg: 5, waterMl: 2, doseMg: 0.25, freq: 5, weeksOn: 12 },
          ])}
        >
          + Add peptide
        </button>
      </div>

      <div className="grid gap-3">
        {rows.map((row, i) => (
          <StackRow
            key={i}
            idx={i}
            data={row}
            onChange={(next: any) => setRows(rows.map((r, idx) => (idx === i ? next : r)))}
            onRemove={() => setRows(rows.filter((_, idx) => idx !== i))}
          />
        ))}
      </div>

      <div className="rounded-2xl border p-4 bg-gray-50">
        <div className="font-semibold">Bottles Needed (by peptide)</div>
        <ul className="mt-2 list-disc pl-5 text-sm space-y-1">
          {summary.map((s, i) => (
            <li key={i}>
              <span className="font-medium">{s.name || `Peptide ${i + 1}`}:</span> ~{s.dosesPerVial.toFixed(1)} shots/vial → {s.bottlesNeeded} bottles
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<'single' | 'stack'>("single");

  return (
    <div className="p-6 md:p-10 font-sans">
      <div className="mx-auto max-w-6xl space-y-6">
        <header className="flex items-center justify-between">
          <h1 className="text-2xl md:text-3xl font-bold">Peptide Protocol Builder</h1>
          <nav className="rounded-xl bg-gray-100 p-1">
            <button
              className={`px-4 py-2 rounded-lg text-sm ${tab === 'single' ? 'bg-white shadow font-semibold' : ''}`}
              onClick={() => setTab('single')}
            >
              Single Peptide
            </button>
            <button
              className={`px-4 py-2 rounded-lg text-sm ${tab === 'stack' ? 'bg-white shadow font-semibold' : ''}`}
              onClick={() => setTab('stack')}
            >
              Stack Builder
            </button>
          </nav>
        </header>

        <p className="text-gray-600 max-w-3xl">
          Pick a peptide (or build a stack), set vial amount and water to mix, and this will calculate U‑100 syringe units per dose, shots per bottle, and bottles needed. The syringe graphic shows exactly where to pull to.
        </p>

        {tab === 'single' ? <SinglePeptideCard /> : <StackBuilder />}

        <footer className="text-xs text-gray-500 pt-8">
          For educational & research use only. Not medical advice.
        </footer>
      </div>
    </div>
  );
}
