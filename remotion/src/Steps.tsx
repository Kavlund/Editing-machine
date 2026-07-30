import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent, withAlpha } from "./util";

export type StepsProps = {
  title?: string;
  steps?: string[];   // 2-4 short steps, in order
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A numbered process (1 -> 2 -> 3) whose rows reveal in sequence. Number badges in
// the client's brand accent; panel + text are neutral so it reads on any footage.
export const Steps: React.FC<StepsProps> = ({ title, steps, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const items = (steps && steps.length ? steps : ["Do the first thing", "Then the next", "Finish strong"]).slice(0, 4);
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;

  const enter = spring({ frame, fps, config: { damping: 14, stiffness: 150, mass: 0.7 } });
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: `0 ${H * 0.06}px` }}>
      <div style={{ opacity: Math.min(enter, fade), width: "100%", maxWidth: H * 0.62, transform: `translateY(${interpolate(enter, [0, 1], [H * 0.04, 0])}px)` }}>
        {title ? (
          <div style={{ fontFamily: font, fontWeight: 900, fontSize: H * 0.036, color: "#fff", letterSpacing: 1, textTransform: "uppercase", marginBottom: H * 0.018, textShadow: "0 2px 10px rgba(0,0,0,0.7)" }}>{title}</div>
        ) : null}
        {items.map((s, i) => {
          const r = spring({ frame: frame - 6 - i * 7, fps, config: { damping: 13, stiffness: 160, mass: 0.6 } });
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: H * 0.02, marginBottom: H * 0.016, opacity: r, transform: `translateX(${interpolate(r, [0, 1], [H * 0.05, 0])}px)` }}>
              <div style={{ flex: "none", width: H * 0.052, height: H * 0.052, borderRadius: "50%", background: ac, color: "#0a0b10", fontFamily: font, fontWeight: 900, fontSize: H * 0.03, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 ${H * 0.006}px ${H * 0.018}px rgba(0,0,0,0.4)` }}>{i + 1}</div>
              <div style={{ flex: 1, background: withAlpha("#0b0d14", 0.9), borderRadius: H * 0.014, padding: `${H * 0.014}px ${H * 0.02}px`, fontFamily: font, fontWeight: 700, fontSize: H * 0.03, color: "#fff", borderLeft: `${H * 0.004}px solid ${ac}` }}>{s}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
