import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent, withAlpha } from "./util";

export type ChecklistProps = {
  title?: string;
  items?: string[];   // 2-5 short items
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A checklist whose boxes tick in one by one, checkmark drawn in the brand accent.
export const Checklist: React.FC<ChecklistProps> = ({ title, items, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const list = (items && items.length ? items : ["Point one", "Point two", "Point three"]).slice(0, 5);
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;

  const enter = spring({ frame, fps, config: { damping: 14, stiffness: 150, mass: 0.7 } });
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const box = H * 0.05;

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: `0 ${H * 0.06}px` }}>
      <div style={{ opacity: Math.min(enter, fade), width: "100%", maxWidth: H * 0.62 }}>
        {title ? (
          <div style={{ fontFamily: font, fontWeight: 900, fontSize: H * 0.036, color: ac, letterSpacing: 1, textTransform: "uppercase", marginBottom: H * 0.018, textShadow: "0 2px 10px rgba(0,0,0,0.7)" }}>{title}</div>
        ) : null}
        {list.map((s, i) => {
          const t0 = 8 + i * 8;
          const tick = interpolate(frame, [t0, t0 + 6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          const rowIn = spring({ frame: frame - i * 8, fps, config: { damping: 14, stiffness: 160, mass: 0.6 } });
          const L = box * 0.6;
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: H * 0.02, marginBottom: H * 0.015, opacity: rowIn }}>
              <div style={{ flex: "none", width: box, height: box, borderRadius: H * 0.01, background: withAlpha("#0b0d14", 0.9), border: `${H * 0.003}px solid ${withAlpha(ac, 0.6 + 0.4 * tick)}`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <svg width={L} height={L} viewBox="0 0 24 24" fill="none" stroke={ac} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 12l5 5L20 6" strokeDasharray={30} strokeDashoffset={30 * (1 - tick)} />
                </svg>
              </div>
              <div style={{ flex: 1, fontFamily: font, fontWeight: 700, fontSize: H * 0.03, color: "#fff", textShadow: "0 2px 8px rgba(0,0,0,0.6)" }}>{s}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
