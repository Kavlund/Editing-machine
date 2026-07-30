import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent, withAlpha } from "./util";

export type QuestionCardProps = {
  question?: string;
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// Poses a question on screen: a big accent "?" mark and the question text under it.
export const QuestionCard: React.FC<QuestionCardProps> = ({ question, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;

  const enter = spring({ frame, fps, config: { damping: 12, stiffness: 160, mass: 0.7 } });
  const qIn = spring({ frame: frame - 6, fps, config: { damping: 10, stiffness: 150, mass: 0.7 } });
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: `0 ${H * 0.07}px` }}>
      <div style={{ opacity: Math.min(enter, fade), textAlign: "center" }}>
        <div style={{ width: H * 0.11, height: H * 0.11, margin: "0 auto", borderRadius: "50%", background: ac, color: "#0a0b10", fontFamily: font, fontWeight: 900, fontSize: H * 0.08, display: "flex", alignItems: "center", justifyContent: "center", transform: `scale(${interpolate(qIn, [0, 1], [0.5, 1])})`, boxShadow: `0 ${H * 0.01}px ${H * 0.03}px rgba(0,0,0,0.45)` }}>?</div>
        <div style={{ marginTop: H * 0.024, fontFamily: font, fontWeight: 800, fontSize: H * 0.046, lineHeight: 1.2, color: "#fff", textShadow: "0 3px 12px rgba(0,0,0,0.6)", background: withAlpha("#0c0e15", 0.4), borderRadius: H * 0.012, padding: `${H * 0.01}px ${H * 0.014}px` }}>{question || "What would you do here?"}</div>
      </div>
    </AbsoluteFill>
  );
};
