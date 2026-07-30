import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent, withAlpha } from "./util";

export type DefinitionProps = {
  term?: string;
  definition?: string;
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A term + its meaning: big accent term, neutral definition line under an accent rule.
export const Definition: React.FC<DefinitionProps> = ({ term, definition, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;

  const enter = spring({ frame, fps, config: { damping: 13, stiffness: 160, mass: 0.7 } });
  const line = interpolate(frame, [6, 18], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const defIn = spring({ frame: frame - 10, fps, config: { damping: 15, stiffness: 150, mass: 0.7 } });
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: `0 ${H * 0.06}px` }}>
      <div style={{ opacity: Math.min(enter, fade), width: "100%", maxWidth: H * 0.64, background: withAlpha("#0c0e15", 0.9), borderRadius: H * 0.016, padding: `${H * 0.03}px ${H * 0.032}px`, transform: `translateY(${interpolate(enter, [0, 1], [H * 0.03, 0])}px)`, boxShadow: `0 ${H * 0.01}px ${H * 0.03}px rgba(0,0,0,0.45)` }}>
        <div style={{ fontFamily: font, fontWeight: 900, fontSize: H * 0.056, color: ac, letterSpacing: 0.5, textShadow: "0 2px 12px rgba(0,0,0,0.5)" }}>{term || "Term"}</div>
        <div style={{ height: H * 0.005, background: ac, borderRadius: 99, margin: `${H * 0.014}px 0`, width: `${line * 100}%`, maxWidth: H * 0.16 }} />
        <div style={{ opacity: defIn, fontFamily: font, fontWeight: 600, fontSize: H * 0.032, lineHeight: 1.25, color: "rgba(255,255,255,0.92)" }}>
          {definition || "A short, plain-language explanation of what it means."}
        </div>
      </div>
    </AbsoluteFill>
  );
};
