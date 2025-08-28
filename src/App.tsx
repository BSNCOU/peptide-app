import { useEffect, useMemo, useState } from "react";

/** --- Sample data (edit to your real list later) --- */
const PEPTIDES = [
  {
    id: "tesa-5",
    name: "Tesamorelin (5 mg)",
    vialMg: 5,
    defaultWaterMl: 2,
    defaultDoseMg: 0.5,
    defaultShotsPerWeek: 5,
    defaultRunWeeks: 12,
    defaultRestWeeks: 4,
  },
  {
    id: "slupp-10",
    name: "SLU-PP-332 (10 mg)",
    vialMg: 10,
    defaultWaterMl: 2,
    defaultDoseMg: 1,
    defaultShotsPerWeek: 5,
    defaultRunWeeks: 8,
    defaultRestWeeks: 4,
  },
  {
    id: "5amq-10",
    name: "5-Amino-1MQ (10 mg)",
    vialMg: 10,
    defaultWaterMl: 2,
    defaultDoseMg: 1,
    defaultShotsPerWeek: 5,
    defaultRunWeeks: 8,
    defaultRestWeeks: 4,
  },
];

/** --- Utils --- */
function fmt(n: number, d = 3) {
  return Number.isFinite(n) ? n.toFixed(d) : "0";
}
function round2(n: number) {
  return Math.round(n * 100) / 100;
}
function clamp(n: number, a: number, b: number) {
  return Math.min(b, Math.max(a, n));
}
async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    alert("Copied!");
  } catch {
    alert("Could not copy. Select and copy manually.");
  }
}

/** U-100 syringe visual (1 mL total), 29G × ½" */
function Syringe({ units }: { units: number }) {
  const width = 360;
  const height = 80;
  const leftPad = 24;
  const rightPad = 24;
  const barrelY = 28;
  const barrelH = 18;
  const barrelX = leftPad;
  const barrelW = width - leftPad - rightPad;

  const xForUnits = (u: number) =>
    barrelX + (Math.max(0, Math.min(100, u)) / 100) * barrelW;

  const ticks: JSX.Element[] = [];
  for (let u = 0; u <= 100; u += 10) {
    const x = xForUnits(u);
    ticks.push(
      <line
        key={`l${u}`}
        x1={x}
        y1={barrelY - 8}
        x2={x}
        y2={barrelY + barrelH + 8}
        stroke="#222"
        strokeWidth={u % 50 === 0 ? 2 : 1}
      />
    );
    ticks.push(
      <text
        key={`t${u}`}
        x={x}
        y={barrelY + barrelH + 24}
        fontSize={10}
        textAnchor="middle"
        fill="#222"
      >
        {u}
      </text>
    );
  }

  const fillW = Math.max(0, xForUnits(units) - barrelX);

  return (
    <svg
      width={width}
      height={height}
      role="img"
      aria-label={`Syringe showing ${units.toFixed(1)} units`}
    >
      {/* Needle */}
      <rect
        x={4}
        y={barrelY + barrelH / 2 - 1}
        width={leftPad - 8}
        height={2}
        fill="#888"
      />
      {/* Barrel */}
      <rect
        x={barrelX}
        y={barrelY}
        width={barrelW}
        height={barrelH}
        rx={3}
        ry={3}
        fill="#f8f8f8"
        stroke="#222"
      />
      {/* Fill */}
      <rect
        x={barrelX}
        y={barrelY}
        width={fillW}
        height={barrelH}
        fill="#cde4ff"
      />
      {/* Plunger cap */}
      <rect
        x={width - rightPad - 6}
        y={barrelY - 6}
        width={10}
        height={barrelH + 12}
        fill="#ddd"
        stroke="#222"
      />
      {/* Ticks + labels */}
      {ticks}
      <text
        x={width - 6}
        y={12}
        fontSize={10}
        textAnchor="end"
        fill="#333"
      >
        U-100 •
