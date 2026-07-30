import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent, withAlpha } from "./util";

export type CommentPromptProps = {
  word?: string;    // the word to comment, e.g. "YES"
  text?: string;    // override the full line
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A chat bubble that pops in asking viewers to comment a specific word (accent chip).
export const CommentPrompt: React.FC<CommentPromptProps> = ({ word, text, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;
  const w = (word || "YES").toUpperCase();

  const enter = spring({ frame, fps, config: { damping: 10, stiffness: 170, mass: 0.6 } });
  const chip = spring({ frame: frame - 8, fps, config: { damping: 9, stiffness: 180, mass: 0.5 } });
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: `0 ${H * 0.06}px` }}>
      <div style={{ opacity: Math.min(enter, fade), transform: `scale(${interpolate(enter, [0, 1], [0.8, 1])})`, position: "relative" }}>
        <div style={{ display: "flex", alignItems: "center", gap: H * 0.016, background: withAlpha("#0c0e15", 0.95), borderRadius: H * 0.024, padding: `${H * 0.02}px ${H * 0.026}px`, boxShadow: `0 ${H * 0.012}px ${H * 0.03}px rgba(0,0,0,0.5)` }}>
          <svg width={H * 0.05} height={H * 0.05} viewBox="0 0 24 24" fill={ac}><path d="M4 4h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H9l-5 4V5a1 1 0 0 1 1-1z" /></svg>
          <div style={{ fontFamily: font, fontWeight: 800, fontSize: H * 0.034, color: "#fff" }}>
            {text ? text : <>Comment <span style={{ display: "inline-block", background: ac, color: "#0a0b10", borderRadius: H * 0.008, padding: `${H * 0.004}px ${H * 0.014}px`, transform: `scale(${chip})`, fontWeight: 900 }}>{w}</span> below</>}
          </div>
        </div>
        <div style={{ position: "absolute", left: H * 0.06, bottom: -H * 0.012, width: 0, height: 0, borderLeft: `${H * 0.016}px solid transparent`, borderRight: `${H * 0.016}px solid transparent`, borderTop: `${H * 0.016}px solid ${withAlpha("#0c0e15", 0.95)}` }} />
      </div>
    </AbsoluteFill>
  );
};
