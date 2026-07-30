import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent, withAlpha } from "./util";

export type KeyTakeawayProps = {
  text?: string;
  label?: string;   // defaults to "KEY TAKEAWAY"
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A labelled panel with an accent tab + left rule that spotlights the one thing to
// remember. Neutral panel, brand-accent framing.
export const KeyTakeaway: React.FC<KeyTakeawayProps> = ({ text, label, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;

  const enter = spring({ frame, fps, config: { damping: 13, stiffness: 160, mass: 0.7 } });
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: `0 ${H * 0.06}px` }}>
      <div style={{ opacity: Math.min(enter, fade), width: "100%", maxWidth: H * 0.64, transform: `scale(${interpolate(enter, [0, 1], [0.94, 1])})` }}>
        <div style={{ display: "inline-block", background: ac, color: "#0a0b10", fontFamily: font, fontWeight: 900, fontSize: H * 0.026, letterSpacing: 2, textTransform: "uppercase", padding: `${H * 0.008}px ${H * 0.018}px`, borderRadius: H * 0.008, marginBottom: H * 0.014 }}>{label || "Key Takeaway"}</div>
        <div style={{ background: withAlpha("#0c0e15", 0.93), borderLeft: `${H * 0.006}px solid ${ac}`, borderRadius: H * 0.012, padding: `${H * 0.026}px ${H * 0.028}px`, fontFamily: font, fontWeight: 800, fontSize: H * 0.042, lineHeight: 1.15, color: "#fff", boxShadow: `0 ${H * 0.01}px ${H * 0.03}px rgba(0,0,0,0.45)` }}>
          {text || "The one thing to remember from this."}
        </div>
      </div>
    </AbsoluteFill>
  );
};
