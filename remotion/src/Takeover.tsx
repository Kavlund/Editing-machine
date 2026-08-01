import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { FONT_FAMILY } from "./font";
import { takeoverTheme } from "./util";
import { NetBackground } from "./NetBackground";

// A full-screen TAKEOVER: the video cuts to the animated net background (in the client's
// primary colour) and the content sits on it. Use this instead of a small card when the
// speaker fills the frame and there is no clean room for an overlay — a list, a key
// statement, or a set of points that deserves the whole screen. `accent` is the client's
// PRIMARY colour, passed by the pipeline.
export type TakeoverProps = {
  kicker?: string;
  title?: string;
  items?: string[];
  bg?: string; // optional surface override; otherwise derived from the brand
  durationInFrames: number;
  width: number;
  height: number;
  accent: string; // the client's PRIMARY brand colour
};

export const Takeover: React.FC<TakeoverProps> = ({ kicker, title, items, bg, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, height } = useVideoConfig();
  const theme = takeoverTheme(accent, bg);
  const net = theme.net; // brand-tone net + kicker + bullets
  const ink = theme.ink; // title + list text (dark on light, white on dark)
  const shadow = theme.isLight ? "0 2px 8px rgba(0,0,0,0.12)" : "0 8px 30px rgba(0,0,0,0.6)";
  const list = items ?? [];

  const fadeOut = interpolate(
    frame,
    [durationInFrames - 12, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const kEnter = spring({ frame, fps, config: { damping: 16, stiffness: 120, mass: 0.8 } });
  const tEnter = spring({ frame: frame - 5, fps, config: { damping: 15, stiffness: 130, mass: 0.7 } });

  return (
    <AbsoluteFill style={{ opacity: fadeOut }}>
      <NetBackground color={net} bg={theme.base} />
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "flex-start",
          padding: `0 ${Math.round(height * 0.06)}px`,
        }}
      >
        {kicker ? (
          <div
            style={{
              opacity: kEnter,
              transform: `translateY(${interpolate(kEnter, [0, 1], [height * 0.02, 0])}px)`,
              fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
              fontWeight: 800,
              fontSize: Math.round(height * 0.023),
              letterSpacing: 3.5,
              textTransform: "uppercase",
              color: net,
              marginBottom: height * 0.022,
            }}
          >
            {kicker}
          </div>
        ) : null}

        {title ? (
          <div
            style={{
              opacity: tEnter,
              transform: `translateY(${interpolate(tEnter, [0, 1], [height * 0.025, 0])}px)`,
              fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
              fontWeight: 900,
              fontSize: Math.round(height * (list.length ? 0.05 : 0.07)),
              lineHeight: 1.05,
              letterSpacing: -0.5,
              textTransform: "uppercase",
              color: ink,
              marginBottom: list.length ? height * 0.036 : 0,
              textShadow: shadow,
            }}
          >
            {title}
          </div>
        ) : null}

        {list.map((item, i) => {
          // Reveal the items PROGRESSIVELY across the takeover's duration, so the list
          // builds as the speaker names each thing (magnesium… aromatherapy… hormones…)
          // rather than all snapping in at once. Spread from ~8% to ~78% of the duration
          // so the last item still has time to read before the outro.
          const revealFrame = Math.round(
            durationInFrames * (0.08 + 0.7 * (i / Math.max(1, list.length)))
          );
          const e = spring({
            frame: frame - revealFrame,
            fps,
            config: { damping: 16, stiffness: 130, mass: 0.7 },
          });
          return (
            <div
              key={i}
              style={{
                opacity: e,
                transform: `translateX(${interpolate(e, [0, 1], [height * 0.03, 0])}px)`,
                display: "flex",
                alignItems: "center",
                gap: height * 0.024,
                marginBottom: height * 0.028,
              }}
            >
              <div
                style={{
                  width: height * 0.02,
                  height: height * 0.02,
                  borderRadius: height * 0.006,
                  backgroundColor: net,
                  boxShadow: theme.isLight ? "none" : `0 0 18px ${net}`,
                  flex: "none",
                }}
              />
              <div
                style={{
                  fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
                  fontWeight: 800,
                  fontSize: Math.round(height * 0.04),
                  lineHeight: 1.16,
                  letterSpacing: -0.5,
                  textTransform: "uppercase",
                  color: ink,
                  textShadow: shadow,
                }}
              >
                {item}
              </div>
            </div>
          );
        })}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
