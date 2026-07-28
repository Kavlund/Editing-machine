import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { FONT_FAMILY } from "./font";

export type LowerThirdProps = {
  name: string;
  subtitle: string;
  durationInFrames: number;
  width: number;
  height: number;
  accent: string;
};

export const LowerThird: React.FC<LowerThirdProps> = ({
  name,
  subtitle,
  accent,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();

  // Ease-out slide in from the left.
  const enter = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 120, mass: 0.9 },
  });
  const enterX = interpolate(enter, [0, 1], [-60, 0]); // percentage of own width

  // Slide + fade out over the last ~10 frames.
  const exitProgress = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const exitX = interpolate(exitProgress, [0, 1], [0, -60]); // slide back left
  const fadeOut = interpolate(exitProgress, [0, 1], [1, 0]);

  const opacity = Math.min(enter, fadeOut);
  const translateXPercent = enterX + exitX;

  const tabWidth = Math.round(width * 0.008);
  const nameSize = Math.round(height * 0.03);
  const subSize = Math.round(height * 0.02);

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-start",
        alignItems: "flex-start",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: height * 0.78,
          left: width * 0.06,
          transform: `translateX(${translateXPercent}%)`,
          opacity,
          display: "flex",
          alignItems: "stretch",
          borderRadius: Math.round(height * 0.012),
          overflow: "hidden",
          backgroundColor: "rgba(0,0,0,0.5)",
          boxShadow: "0 10px 34px rgba(0,0,0,0.45)",
        }}
      >
        {/* colored accent tab on the left edge */}
        <div
          style={{
            width: tabWidth,
            minWidth: tabWidth,
            backgroundColor: accent,
          }}
        />
        <div
          style={{
            padding: `${Math.round(height * 0.016)}px ${Math.round(
              width * 0.028,
            )}px`,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
          }}
        >
          <div
            style={{
              fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
              fontWeight: 700,
              fontSize: nameSize,
              lineHeight: 1.05,
              color: "#ffffff",
              textTransform: "uppercase",
              letterSpacing: "0.02em",
              textShadow: "0 3px 12px rgba(0,0,0,0.6)",
              whiteSpace: "nowrap",
            }}
          >
            {name}
          </div>
          <div
            style={{
              marginTop: Math.round(height * 0.006),
              fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
              fontWeight: 400,
              fontSize: subSize,
              lineHeight: 1.1,
              color: accent,
              letterSpacing: "0.04em",
              textShadow: "0 2px 10px rgba(0,0,0,0.6)",
              whiteSpace: "nowrap",
            }}
          >
            {subtitle}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
