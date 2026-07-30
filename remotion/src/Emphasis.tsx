import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { readableAccent } from "./util";

export type EmphasisProps = {
  mode?: "circle" | "underline" | "arrow"; // draw-on style
  cx?: number;   // target center x, 0..1 of width  (default 0.5)
  cy?: number;   // target center y, 0..1 of height (default 0.5)
  accent: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A marker-style draw-on emphasis: a hand-drawn circle, an underline sweep, or
// a pointing arrow, all in the brand accent. Draws in, holds, fades out.
export const Emphasis: React.FC<EmphasisProps> = ({ mode, cx, cy, accent, width, height }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const W = width;
  const H = height;
  const clamp01 = (v: number | undefined, d: number) => {
    const n = typeof v === "number" ? v : parseFloat(String(v));
    return isFinite(n) ? Math.max(0.08, Math.min(0.92, n)) : d;
  };
  const px = clamp01(cx, 0.5) * W;
  const py = clamp01(cy, 0.5) * H;
  const m = mode || "circle";

  const draw = interpolate(frame, [2, 20], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const fade = interpolate(frame, [durationInFrames - 9, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const stroke = Math.max(4, H * 0.006);

  let path = "";
  let len = 1000;
  if (m === "circle") {
    const rx = W * 0.22;
    const ry = H * 0.09;
    // slightly open, hand-drawn ellipse
    path = `M ${px + rx * 0.9} ${py - ry * 0.5}
            C ${px + rx} ${py - ry}, ${px - rx} ${py - ry}, ${px - rx} ${py}
            C ${px - rx} ${py + ry}, ${px + rx} ${py + ry}, ${px + rx * 0.95} ${py + ry * 0.35}`;
    len = 2 * Math.PI * Math.sqrt((rx * rx + ry * ry) / 2);
  } else if (m === "underline") {
    const w = W * 0.34;
    path = `M ${px - w} ${py} q ${w * 0.5} ${H * 0.03}, ${w} ${-H * 0.004} q ${w * 0.5} ${-H * 0.03}, ${w} ${H * 0.006}`;
    len = w * 2.2;
  } else {
    // arrow: shaft plus head, pointing toward (px,py) from lower-left
    const x0 = px - W * 0.22;
    const y0 = py + H * 0.14;
    path = `M ${x0} ${y0} Q ${px - W * 0.06} ${py + H * 0.02}, ${px - W * 0.03} ${py - H * 0.01}
            M ${px - W * 0.03} ${py - H * 0.01} l ${-W * 0.045} ${H * 0.002}
            M ${px - W * 0.03} ${py - H * 0.01} l ${W * 0.006} ${H * 0.05}`;
    len = W * 0.34;
  }

  return (
    <AbsoluteFill style={{ opacity: fade }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", inset: 0 }}>
        <path
          d={path}
          fill="none"
          stroke={ac}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray={len}
          strokeDashoffset={len * (1 - draw)}
          style={{ filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.45))" }}
        />
      </svg>
    </AbsoluteFill>
  );
};
