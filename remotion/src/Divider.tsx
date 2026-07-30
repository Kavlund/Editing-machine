import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent } from "./util";

export type DividerProps = {
  text?: string;    // the section title
  kicker?: string;  // small line above, e.g. "PART 2"
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A section / chapter marker: a centred title framed by accent rules that draw out.
export const Divider: React.FC<DividerProps> = ({ text, kicker, accent, width, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const W = width;
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;

  const enter = spring({ frame, fps, config: { damping: 14, stiffness: 150, mass: 0.7 } });
  const rule = interpolate(frame, [4, 20], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const ruleW = rule * W * 0.16;

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: `0 ${H * 0.05}px` }}>
      <div style={{ opacity: Math.min(enter, fade), textAlign: "center" }}>
        {kicker ? (
          <div style={{ fontFamily: font, fontWeight: 800, fontSize: H * 0.024, color: ac, letterSpacing: 4, textTransform: "uppercase", marginBottom: H * 0.014 }}>{kicker}</div>
        ) : null}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: H * 0.022 }}>
          <div style={{ height: H * 0.004, width: ruleW, background: ac, borderRadius: 99 }} />
          <div style={{ fontFamily: font, fontWeight: 900, fontSize: H * 0.05, color: "#fff", letterSpacing: 1, textTransform: "uppercase", textShadow: "0 3px 12px rgba(0,0,0,0.6)", whiteSpace: "nowrap" }}>{text || "Next Up"}</div>
          <div style={{ height: H * 0.004, width: ruleW, background: ac, borderRadius: 99 }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
