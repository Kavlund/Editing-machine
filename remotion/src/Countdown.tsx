import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent, withAlpha } from "./util";

export type CountdownProps = {
  label?: string;   // "ENDS IN"
  value?: string;   // "24:00:00" or "3 DAYS"
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// An urgency block: a big brand-accent value on a soft pulse under a small label.
export const Countdown: React.FC<CountdownProps> = ({ label, value, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;

  const enter = spring({ frame, fps, config: { damping: 11, stiffness: 160, mass: 0.7 } });
  const pulse = 1 + 0.03 * Math.sin((frame / fps) * 5.5);
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <div style={{ opacity: Math.min(enter, fade), transform: `scale(${interpolate(enter, [0, 1], [0.85, 1]) * pulse})`, textAlign: "center" }}>
        <div style={{ fontFamily: font, fontWeight: 900, fontSize: H * 0.028, color: "#fff", letterSpacing: 3, textTransform: "uppercase", marginBottom: H * 0.012, textShadow: "0 2px 8px rgba(0,0,0,0.7)" }}>{label || "Ends In"}</div>
        <div style={{ display: "inline-block", background: withAlpha("#0c0e15", 0.94), border: `${H * 0.004}px solid ${ac}`, borderRadius: H * 0.018, padding: `${H * 0.016}px ${H * 0.036}px`, fontFamily: font, fontWeight: 900, fontSize: H * 0.09, color: ac, letterSpacing: 2, fontVariantNumeric: "tabular-nums", textShadow: `0 0 ${H * 0.03}px ${withAlpha(ac, 0.6)}`, boxShadow: `0 ${H * 0.01}px ${H * 0.03}px rgba(0,0,0,0.5)` }}>{value || "24:00:00"}</div>
      </div>
    </AbsoluteFill>
  );
};
