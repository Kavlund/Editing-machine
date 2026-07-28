import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { FONT_FAMILY } from "./font";

export type ComparisonProps = {
  leftLabel: string;
  leftText: string;
  rightLabel: string;
  rightText: string;
  durationInFrames: number;
  width: number;
  height: number;
  accent: string;
};

// Muted red-ish tint for the negative/left side label. Fixed (not the accent)
// so the "before / myth / X" side always reads as the down-beat option.
const NEGATIVE = "#FF6B6B";

export const Comparison: React.FC<ComparisonProps> = ({
  leftLabel,
  leftText,
  rightLabel,
  rightText,
  accent,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, height } = useVideoConfig();

  // Global fade out over the last ~10 frames.
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // Left/negative panel springs in first.
  const leftEnter = spring({
    frame,
    fps,
    config: { damping: 15, stiffness: 130, mass: 0.7 },
  });
  const leftShift = interpolate(leftEnter, [0, 1], [-height * 0.05, 0]);

  // Right/positive panel follows a few frames later.
  const rightDelay = 9;
  const rightEnter = spring({
    frame: frame - rightDelay,
    fps,
    config: { damping: 15, stiffness: 130, mass: 0.7 },
  });
  const rightShift = interpolate(rightEnter, [0, 1], [height * 0.05, 0]);

  const panelBase: React.CSSProperties = {
    width: "82%",
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    gap: height * 0.012,
    padding: `${height * 0.03}px ${height * 0.042}px`,
    backgroundColor: "rgba(0,0,0,0.42)",
    borderRadius: height * 0.02,
    boxShadow: "0 18px 60px rgba(0,0,0,0.45)",
    boxSizing: "border-box",
  };

  const labelBase: React.CSSProperties = {
    fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
    fontWeight: 700,
    fontSize: Math.round(height * 0.03),
    lineHeight: 1.05,
    letterSpacing: 2,
    textTransform: "uppercase",
    textShadow: "0 4px 16px rgba(0,0,0,0.6)",
  };

  const textBase: React.CSSProperties = {
    fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
    fontWeight: 700,
    fontSize: Math.round(height * 0.04),
    lineHeight: 1.12,
    letterSpacing: -0.5,
    color: "#FFFFFF",
    textTransform: "uppercase",
    textShadow: "0 8px 28px rgba(0,0,0,0.55), 0 2px 6px rgba(0,0,0,0.7)",
  };

  return (
    <AbsoluteFill
      style={{
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        gap: height * 0.03,
      }}
    >
      {/* Negative / left side */}
      <div
        style={{
          ...panelBase,
          opacity: Math.min(leftEnter, fadeOut),
          transform: `translateY(${leftShift}px)`,
          border: "1px solid rgba(255,107,107,0.35)",
        }}
      >
        <div style={{ ...labelBase, color: NEGATIVE }}>{leftLabel}</div>
        <div style={textBase}>{leftText}</div>
      </div>

      {/* Positive / right side */}
      <div
        style={{
          ...panelBase,
          opacity: Math.min(rightEnter, fadeOut),
          transform: `translateY(${rightShift}px)`,
          border: `1px solid ${accent}59`,
        }}
      >
        <div style={{ ...labelBase, color: accent }}>{rightLabel}</div>
        <div style={textBase}>{rightText}</div>
      </div>
    </AbsoluteFill>
  );
};
