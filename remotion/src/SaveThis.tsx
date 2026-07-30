import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent } from "./util";

export type SaveThisProps = {
  text?: string;   // defaults to "SAVE THIS"
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A bookmark that pops and fills in the brand accent — "save this for later".
export const SaveThis: React.FC<SaveThisProps> = ({ text, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;

  const enter = spring({ frame, fps, config: { damping: 10, stiffness: 170, mass: 0.6 } });
  const fill = interpolate(frame, [10, 22], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const bob = Math.sin((frame / fps) * 5) * H * 0.004;
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: H * 0.17 }}>
      <div style={{ opacity: Math.min(enter, fade), display: "flex", alignItems: "center", gap: H * 0.018, background: "rgba(12,14,21,0.95)", borderRadius: H * 0.5, padding: `${H * 0.014}px ${H * 0.032}px`, transform: `scale(${interpolate(enter, [0, 1], [0.7, 1])}) translateY(${bob}px)`, boxShadow: `0 ${H * 0.012}px ${H * 0.03}px rgba(0,0,0,0.5)` }}>
        <svg width={H * 0.04} height={H * 0.04} viewBox="0 0 24 24" fill={fill > 0.5 ? ac : "none"} stroke={ac} strokeWidth={2.5} strokeLinejoin="round">
          <path d="M6 3h12a1 1 0 0 1 1 1v17l-7-5-7 5V4a1 1 0 0 1 1-1z" />
        </svg>
        <div style={{ fontFamily: font, fontWeight: 900, fontSize: H * 0.03, color: "#fff", letterSpacing: 1, textTransform: "uppercase" }}>{text || "Save this"}</div>
      </div>
    </AbsoluteFill>
  );
};
