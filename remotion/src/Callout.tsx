import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent } from "./util";

export type CalloutProps = {
  text?: string;        // the phrase to punch in
  accent: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// Kinetic emphasis text: an accent highlight bar sweeps in behind a bold phrase
// that punches up. For pulling a spoken line out on screen.
export const Callout: React.FC<CalloutProps> = ({ text, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const label = (text || "THIS CHANGES EVERYTHING").toUpperCase();

  const enter = spring({ frame, fps, config: { damping: 12, stiffness: 170, mass: 0.6 } });
  const y = interpolate(enter, [0, 1], [H * 0.06, 0]);
  const sweep = interpolate(frame, [4, 18], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const fade = interpolate(frame, [durationInFrames - 9, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: `0 ${H * 0.05}px` }}>
      <div style={{ position: "relative", transform: `translateY(${y}px)`, opacity: Math.min(enter, fade) }}>
        <div
          style={{
            position: "absolute",
            left: -H * 0.02,
            right: -H * 0.02,
            top: "12%",
            bottom: "12%",
            background: ac,
            borderRadius: H * 0.012,
            transform: `scaleX(${sweep})`,
            transformOrigin: "left center",
          }}
        />
        <span
          style={{
            position: "relative",
            fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
            fontWeight: 900,
            fontSize: H * 0.05,
            lineHeight: 1.05,
            color: sweep > 0.75 ? "#0a0b10" : "#ffffff",
            letterSpacing: 0.5,
            textAlign: "center",
            display: "block",
            padding: `${H * 0.006}px ${H * 0.01}px`,
            textShadow: sweep > 0.75 ? "none" : "0 3px 12px rgba(0,0,0,0.6)",
          }}
        >
          {label}
        </span>
      </div>
    </AbsoluteFill>
  );
};
