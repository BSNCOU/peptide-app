import React, { useEffect, useMemo, useState } from "react";

/** --- Sample options (swap with your real list later) --- */
type Peptide = {
  id: string;
  name: string;            // display name
  vialMg: number;          // total mg in vial
  defaultWaterMl: number;  // mL of bac water to add
  defaultDoseMg: number;   // mg per injection
  defaultShotsPerWeek: number;
  defaultRunWeeks: number;
  defaultRestWeeks: number;
};

const PEPTIDES: Peptide[] = [
  { id: "tesa-5",   name: "Tesamorelin (5 mg)", vialMg: 5,  defaultWaterMl: 2, defaultDoseMg: 0.5, defaultShotsPerWeek: 5, defaultRunWeeks: 12, defaultRestWeeks: 4 },
  { id: "slupp-10", name: "SLU-PP-332 (10 mg)", vialMg: 10, defaultWaterMl: 2, defaultDoseMg: 1.0, defaultShotsPerWeek: 5, defaultRunWeeks: 8,  defaultRestWeeks: 4 },
  { id: "5amq-10",  name: "5-Amino-1MQ (10 mg)", vialMg: 10, defaultWaterMl: 2, defaultDoseMg: 1.0, defaultShotsPerWeek: 5, defaultRunWeeks: 8,  defaultRestWeeks: 4 },
];

/** --- Small utils --- */
const fmt = (n: number, d = 3) => (Number.isFinite(n) ? n.toFixed(d) : "0");
const round2 = (n: number) => Math.round(n * 100) / 100;
const clamp = (n: number, a: number, b: number) => Math.min(b, Math.max(a, n));
async function copyToClipboard(text: string) {
  try { await navigator.clipboard.writeText(text); alert("Copied!"); }
  catch { alert("Couldn’t copy—select and copy manually."); }
}

/** --- U-100 syringe (1 mL) visual, 29G × 1/2" --- */
function Syringe({ units }: { units: number }) {
  const width = 360, height = 80;
  const leftPad = 24, rightPad = 24;
