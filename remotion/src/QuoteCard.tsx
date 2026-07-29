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

export type QuoteCardProps = {
  quote: string;
  attribution?: string;
  durationInFrames: number;
  width: number;
  height: number;
  accent: string;
};

export const QuoteCard: React.FC<QuoteCardProps> = ({
  quote,
  attribution,
  accent,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();
  const ac = readableAccent(accent);

  // 1) Big decorative opening quotation mark scales + fades in first.
  const markEnter = spring({
    frame,
    fps,
    config: { damping: 12, stiffness: 120, mass: 0.8 },
  });
  const markScale = interpolate(markEnter, [0, 1], [0.4, 1]);

  // 2) Quote text fades up shortly after the mark lands.
  const quoteEnter = spring({
    frame,
    fps,
    delay: 8,
    config: { damping: 16, stiffness: 110, mass: 0.9 },
  });
  const quoteY = interpolate(quoteEnter, [0, 1], [height * 0.03, 0]);

  // 3) Attribution slides in under the quote last.
  const attribEnter = spring({
    frame,
    fps,
    delay: 20,
    config: { damping: 18, stiffness: 120, mass: 0.9 },
  });
  const attribX = interpolate(attribEnter, [0, 1], [-height * 0.03, 0]);

  // Whole card fades in with the mark and fades out over the last ~10 frames.
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const cardOpacity = Math.min(markEnter, fadeOut);

  const quoteSize = Math.round(height * 0.045);
  const markSize = Math.round(height * 0.13);
  const attribSize = Math.round(height * 0.024);
  const panelRadius = Math.round(height * 0.02);

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <div
        style={{
          opacity: cardOpacity,
          maxWidth: width * 0.78,
          padding: `${Math.round(height * 0.05)}px ${Math.round(
            width * 0.06,
          )}px ${Math.round(height * 0.045)}px`,
          borderRadius: panelRadius,
          backgroundColor: "rgba(10,12,16,0.8)",
          boxShadow: "0 18px 60px rgba(0,0,0,0.45)",
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
        }}
      >
        {/* Decorative opening quotation mark */}
        <div
          style={{
            transform: `scale(${markScale})`,
            transformOrigin: "left center",
            opacity: markEnter,
            marginTop: -markSize * 0.55,
            marginBottom: -markSize * 0.28,
            fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
            fontWeight: 700,
            fontSize: markSize,
            lineHeight: 1,
            color: ac,
            textShadow: "0 8px 24px rgba(0,0,0,0.5)",
          }}
        >
          {"“"}
        </div>

        {/* Quote text — sentence case, large and readable */}
        <div
          style={{
            transform: `translateY(${quoteY}px)`,
            opacity: quoteEnter,
            fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
            fontWeight: 700,
            fontSize: quoteSize,
            lineHeight: 1.18,
            letterSpacing: "-0.01em",
            color: "#ffffff",
            textShadow: "0 6px 22px rgba(0,0,0,0.6), 0 2px 6px rgba(0,0,0,0.7)",
          }}
        >
          {quote}
        </div>

        {/* Attribution slides in beneath the quote */}
        {attribution ? (
          <div
            style={{
              transform: `translateX(${attribX}px)`,
              opacity: attribEnter,
              marginTop: Math.round(height * 0.028),
              display: "flex",
              alignItems: "center",
              gap: Math.round(width * 0.014),
              fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
              fontWeight: 400,
              fontSize: attribSize,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: ac,
              textShadow: "0 2px 10px rgba(0,0,0,0.6)",
            }}
          >
            <span
              style={{
                width: Math.round(width * 0.035),
                height: Math.max(2, Math.round(height * 0.003)),
                backgroundColor: ac,
                borderRadius: 999,
              }}
            />
            {attribution}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
