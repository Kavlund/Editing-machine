import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent } from "./util";

export type HookProps = {
  text: string;
  durationInFrames: number;
  width: number;
  height: number;
  accent: string;
};

export const Hook: React.FC<HookProps> = ({ text, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, height } = useVideoConfig();

  const enter = spring({ frame, fps, config: { damping: 13, stiffness: 130, mass: 0.7 } });
  const scale = interpolate(enter, [0, 1], [0.8, 1]);
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const opacity = Math.min(enter, fadeOut);

  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center", paddingTop: height * 0.2 }}>
      <div
        style={{
          transform: `scale(${scale})`,
          opacity,
          maxWidth: "84%",
          textAlign: "center",
          fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
          fontWeight: 700,
          fontSize: Math.round(height * 0.052),
          lineHeight: 1.03,
          letterSpacing: -1,
          color: readableAccent(accent),
          textTransform: "uppercase",
          textShadow: "0 8px 28px rgba(0,0,0,0.55), 0 2px 6px rgba(0,0,0,0.7)",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
