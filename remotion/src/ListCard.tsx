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

export type ListCardProps = {
  title?: string;
  items: string[];
  durationInFrames: number;
  width: number;
  height: number;
  accent: string;
};

export const ListCard: React.FC<ListCardProps> = ({ title, items, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, height } = useVideoConfig();
  const ac = readableAccent(accent);

  // Whole-card entrance (panel springs/scales in)
  const enter = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 120, mass: 0.8 },
  });
  const cardScale = interpolate(enter, [0, 1], [0.9, 1]);

  // Global fade out over the last ~10 frames
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // Title reveal first
  const titleEnter = spring({
    frame,
    fps,
    config: { damping: 15, stiffness: 130, mass: 0.7 },
  });
  const titleOpacity = interpolate(titleEnter, [0, 1], [0, 1]);
  const titleShift = interpolate(titleEnter, [0, 1], [height * 0.02, 0]);

  const safeItems = items ?? [];

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <div
        style={{
          transform: `scale(${cardScale})`,
          opacity: Math.min(enter, fadeOut),
          maxWidth: "82%",
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          gap: height * 0.018,
          padding: `${height * 0.038}px ${height * 0.05}px`,
          backgroundColor: "rgba(10,12,16,0.82)",
          border: `1px solid ${ac}33`,
          borderRadius: height * 0.02,
          boxShadow: "0 18px 60px rgba(0,0,0,0.55)",
        }}
      >
        {title ? (
          <div
            style={{
              opacity: titleOpacity,
              transform: `translateY(${titleShift}px)`,
              fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
              fontWeight: 700,
              fontSize: Math.round(height * 0.03),
              lineHeight: 1.1,
              letterSpacing: 0.5,
              color: "rgba(255,255,255,0.82)",
              textTransform: "uppercase",
              marginBottom: height * 0.008,
              textShadow: "0 4px 16px rgba(0,0,0,0.6)",
            }}
          >
            {title}
          </div>
        ) : null}

        {safeItems.map((item, i) => {
          // Stagger: title first, then each item offset by ~7 frames
          const delay = 8 + i * 7;
          const itemEnter = spring({
            frame: frame - delay,
            fps,
            config: { damping: 15, stiffness: 130, mass: 0.7 },
          });
          const itemOpacity = interpolate(itemEnter, [0, 1], [0, 1]);
          const itemShift = interpolate(itemEnter, [0, 1], [height * 0.028, 0]);

          return (
            <div
              key={i}
              style={{
                opacity: itemOpacity,
                transform: `translateY(${itemShift}px)`,
                display: "flex",
                alignItems: "flex-start",
                gap: height * 0.02,
              }}
            >
              <div
                style={{
                  width: height * 0.017,
                  height: height * 0.017,
                  borderRadius: 4,
                  backgroundColor: ac,
                  marginTop: height * 0.019,
                  flex: "none",
                  boxShadow: `0 0 14px ${ac}aa`,
                }}
              />
              <div
                style={{
                  fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
                  fontWeight: 700,
                  fontSize: Math.round(height * 0.044),
                  lineHeight: 1.18,
                  letterSpacing: -0.5,
                  color: "#ffffff",
                  textTransform: "uppercase",
                  textShadow:
                    "0 8px 28px rgba(0,0,0,0.6), 0 2px 6px rgba(0,0,0,0.75)",
                }}
              >
                {item}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
