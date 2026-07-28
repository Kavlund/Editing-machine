import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { FONT_FAMILY } from "./font";

export type StatProps = {
  value: string;
  label: string;
  durationInFrames: number;
  width: number;
  height: number;
  accent: string;
};

export const Stat: React.FC<StatProps> = ({ value, label, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, height } = useVideoConfig();

  // Value pops in BIG and punchy with a lively, slightly-overshooting spring.
  const valueEnter = spring({
    frame,
    fps,
    config: { damping: 10, stiffness: 170, mass: 0.6 },
  });
  const valueScale = interpolate(valueEnter, [0, 1], [0.6, 1]);

  // Label fades up a few frames later, gently rising into place.
  const labelDelay = 6;
  const labelEnter = spring({
    frame: frame - labelDelay,
    fps,
    config: { damping: 16, stiffness: 130, mass: 0.7 },
  });
  const labelRise = interpolate(labelEnter, [0, 1], [height * 0.03, 0]);

  const fadeOut = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const valueOpacity = Math.min(valueEnter, fadeOut);
  const labelOpacity = Math.min(labelEnter, fadeOut);

  return (
    <AbsoluteFill
      style={{
        flexDirection: "column",
        justifyContent: "flex-start",
        alignItems: "center",
        paddingTop: height * 0.24,
      }}
    >
      <div
        style={{
          transform: `scale(${valueScale})`,
          opacity: valueOpacity,
          fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
          fontWeight: 700,
          fontSize: Math.round(height * 0.13),
          lineHeight: 1,
          letterSpacing: -2,
          color: accent,
          textShadow:
            "0 12px 40px rgba(0,0,0,0.6), 0 3px 8px rgba(0,0,0,0.75)",
        }}
      >
        {value}
      </div>
      <div
        style={{
          transform: `translateY(${labelRise}px)`,
          opacity: labelOpacity,
          marginTop: height * 0.018,
          maxWidth: "80%",
          textAlign: "center",
          fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
          fontWeight: 700,
          fontSize: Math.round(height * 0.03),
          lineHeight: 1.15,
          letterSpacing: 3,
          color: "#FFFFFF",
          textTransform: "uppercase",
          textShadow:
            "0 6px 20px rgba(0,0,0,0.55), 0 2px 5px rgba(0,0,0,0.7)",
        }}
      >
        {label}
      </div>
    </AbsoluteFill>
  );
};
