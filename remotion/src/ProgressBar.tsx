import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent, withAlpha } from "./util";

export type ProgressBarProps = {
  label?: string;      // what the bar measures
  value?: string;      // "70%" or "7/10" or a number
  caption?: string;    // small note under the bar
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A labelled meter that fills to its value in the client's brand accent.
export const ProgressBar: React.FC<ProgressBarProps> = ({ label, value, caption, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;
  const raw = value || "70%";
  const num = parseFloat(String(raw).replace(/[^0-9.]/g, ""));
  const frac = /%/.test(raw) ? Math.max(0, Math.min(1, (isFinite(num) ? num : 70) / 100))
            : /\//.test(raw) ? (() => { const [a, b] = raw.split("/").map((x) => parseFloat(x)); return b ? Math.max(0, Math.min(1, a / b)) : 0.7; })()
            : Math.max(0, Math.min(1, (isFinite(num) ? num : 70) / 100));

  const enter = spring({ frame, fps, config: { damping: 14, stiffness: 150, mass: 0.7 } });
  const fill = spring({ frame: frame - 6, fps, config: { damping: 200, stiffness: 55, mass: 1 } });
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const w = fill * frac;

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: `0 ${H * 0.07}px` }}>
      <div style={{ opacity: Math.min(enter, fade), width: "100%", maxWidth: H * 0.6, transform: `translateY(${interpolate(enter, [0, 1], [H * 0.04, 0])}px)` }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: H * 0.014 }}>
          <span style={{ fontFamily: font, fontWeight: 800, fontSize: H * 0.032, color: "#fff", textShadow: "0 2px 8px rgba(0,0,0,0.7)" }}>{label || "Progress"}</span>
          <span style={{ fontFamily: font, fontWeight: 900, fontSize: H * 0.05, color: ac, textShadow: "0 2px 10px rgba(0,0,0,0.5)" }}>{raw}</span>
        </div>
        <div style={{ height: H * 0.03, borderRadius: H * 0.02, background: withAlpha("#0b0d14", 0.92), overflow: "hidden", boxShadow: "inset 0 2px 6px rgba(0,0,0,0.5)" }}>
          <div style={{ height: "100%", width: `${w * 100}%`, background: ac, borderRadius: H * 0.02, boxShadow: `0 0 ${H * 0.02}px ${withAlpha(ac, 0.7)}` }} />
        </div>
        {caption ? (
          <div style={{ marginTop: H * 0.012, fontFamily: font, fontWeight: 700, fontSize: H * 0.022, color: "rgba(255,255,255,0.85)", textShadow: "0 2px 8px rgba(0,0,0,0.7)" }}>{caption}</div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
