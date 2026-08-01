import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { withAlpha, shade, lum } from "./util";

// A full-frame animated "net" / plexus background: drifting nodes joined by lines
// where they are near, over a near-black field with a soft brand-tinted glow. This is
// the full-screen takeover backdrop for moments where a small card over the live
// speaker would collide with the face — the video cuts to this and the content sits on
// it. Opaque, so it covers the frame. Drawn in the client's colour (lightened only if
// too dark to read on black), so it always reads as on-brand.
//
// Determinism matters: Remotion renders frame-by-frame and must be pure, so node homes
// come from a seeded hash (not Math.random) and motion is sin/cos of the clock.
function rnd(seed: number): number {
  const x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

export const NetBackground: React.FC<{
  color: string; // the net line/dot colour (already theme-resolved for contrast)
  bg: string; // the surface colour behind the net
  count?: number;
}> = ({ color, bg, count = 30 }) => {
  const frame = useCurrentFrame();
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const ac = color;
  const surfaceLight = lum(bg) >= 0.5;
  const t = frame / fps;

  const nodes: { x: number; y: number }[] = [];
  for (let i = 0; i < count; i++) {
    const hx = rnd(i * 2 + 1);
    const hy = rnd(i * 2 + 2);
    const sp = 0.12 + rnd(i + 7) * 0.22; // per-node drift speed
    const ph = rnd(i + 13) * Math.PI * 2;
    const ax = (0.04 + rnd(i + 21) * 0.06) * width; // drift amplitude
    const ay = (0.04 + rnd(i + 29) * 0.06) * height;
    nodes.push({
      x: hx * width + Math.sin(t * sp + ph) * ax,
      y: hy * height + Math.cos(t * sp * 0.9 + ph) * ay,
    });
  }

  const maxD = Math.min(width, height) * 0.28;
  const lines: { a: number; b: number; o: number }[] = [];
  for (let i = 0; i < count; i++) {
    for (let j = i + 1; j < count; j++) {
      const dx = nodes[i].x - nodes[j].x;
      const dy = nodes[i].y - nodes[j].y;
      const d = Math.sqrt(dx * dx + dy * dy);
      if (d < maxD) lines.push({ a: i, b: j, o: 1 - d / maxD });
    }
  }

  const fin = Math.min(1, frame / 10);
  const fout = Math.min(1, (durationInFrames - frame) / 10);
  const g = Math.max(0, Math.min(fin, fout));
  const r = Math.max(2, Math.round(Math.min(width, height) * 0.004));

  return (
    <svg
      width={width}
      height={height}
      style={{ position: "absolute", inset: 0, display: "block" }}
    >
      <defs>
        <radialGradient id="netglow" cx="50%" cy="40%" r="72%">
          <stop offset="0%" stopColor={withAlpha(ac, surfaceLight ? 0.1 : 0.18)} />
          <stop offset="55%" stopColor={withAlpha(shade(ac, -0.5), 0.05)} />
          <stop offset="100%" stopColor="rgba(0,0,0,0)" />
        </radialGradient>
      </defs>
      <rect x={0} y={0} width={width} height={height} fill={bg} />
      <rect x={0} y={0} width={width} height={height} fill="url(#netglow)" />
      <g opacity={g}>
        {lines.map((l, k) => (
          <line
            key={k}
            x1={nodes[l.a].x}
            y1={nodes[l.a].y}
            x2={nodes[l.b].x}
            y2={nodes[l.b].y}
            stroke={ac}
            strokeWidth={1.3}
            opacity={l.o * (surfaceLight ? 0.34 : 0.3)}
          />
        ))}
        {nodes.map((n, k) => (
          <circle key={k} cx={n.x} cy={n.y} r={r} fill={ac} opacity={surfaceLight ? 0.62 : 0.6} />
        ))}
      </g>
    </svg>
  );
};
