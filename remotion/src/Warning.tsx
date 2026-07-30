import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent, withAlpha } from "./util";

export type WarningProps = {
  text?: string;
  label?: string;   // defaults to "WATCH OUT"
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A "don't do this" caution card. Conveys alert via a bold ! badge, a shake-in and
// an accent frame — brand-coloured, not a fixed red, so it stays personalised.
export const Warning: React.FC<WarningProps> = ({ text, label, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;

  const enter = spring({ frame, fps, config: { damping: 10, stiffness: 170, mass: 0.6 } });
  const shake = frame < 22 ? Math.sin(frame * 1.4) * (1 - frame / 22) * H * 0.006 : 0;
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: `0 ${H * 0.06}px` }}>
      <div style={{ opacity: Math.min(enter, fade), width: "100%", maxWidth: H * 0.64, transform: `translateX(${shake}px) scale(${interpolate(enter, [0, 1], [0.9, 1])})`, background: withAlpha("#0c0e15", 0.94), border: `${H * 0.004}px solid ${ac}`, borderRadius: H * 0.016, padding: `${H * 0.026}px ${H * 0.028}px`, display: "flex", alignItems: "center", gap: H * 0.024, boxShadow: `0 ${H * 0.01}px ${H * 0.03}px rgba(0,0,0,0.5)` }}>
        <div style={{ flex: "none", width: H * 0.07, height: H * 0.07, borderRadius: H * 0.014, background: ac, color: "#0a0b10", fontFamily: font, fontWeight: 900, fontSize: H * 0.05, display: "flex", alignItems: "center", justifyContent: "center" }}>!</div>
        <div>
          <div style={{ fontFamily: font, fontWeight: 900, fontSize: H * 0.026, color: ac, letterSpacing: 2, textTransform: "uppercase", marginBottom: H * 0.006 }}>{label || "Watch Out"}</div>
          <div style={{ fontFamily: font, fontWeight: 800, fontSize: H * 0.036, lineHeight: 1.15, color: "#fff" }}>{text || "The mistake most people make here."}</div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
