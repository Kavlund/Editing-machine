import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent } from "./util";

export type CounterProps = {
  value?: string;       // final number, e.g. "10,000" or "87%"
  label?: string;       // caption under the number
  prefix?: string;      // e.g. "$"
  suffix?: string;      // e.g. "+"
  accent: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A big number that counts up to its target, with a label underneath.
// Parses digits out of `value`, animates them, keeps any formatting.
export const Counter: React.FC<CounterProps> = ({ value, label, prefix, suffix, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;

  const raw = value || "10,000";
  const digits = raw.replace(/[^0-9]/g, "");
  const target = digits ? parseInt(digits, 10) : 0;
  const hasPercent = /%/.test(raw);
  const grouped = /,/.test(raw);

  const prog = spring({ frame, fps, config: { damping: 200, stiffness: 60, mass: 1 } });
  const current = Math.round(target * prog);
  const shown = grouped ? current.toLocaleString("en-US") : String(current);

  const pop = spring({ frame, fps, config: { damping: 11, stiffness: 150, mass: 0.7 } });
  const scale = interpolate(pop, [0, 1], [0.6, 1]);
  const fade = interpolate(frame, [durationInFrames - 9, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <div style={{ transform: `scale(${scale})`, opacity: Math.min(pop, fade), textAlign: "center" }}>
        <div
          style={{
            fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
            fontWeight: 900,
            fontSize: H * 0.13,
            lineHeight: 1,
            color: ac,
            letterSpacing: -1,
            textShadow: "0 4px 18px rgba(0,0,0,0.55)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {prefix || ""}
          {shown}
          {hasPercent ? "%" : ""}
          {suffix || ""}
        </div>
        {label ? (
          <div
            style={{
              marginTop: H * 0.012,
              fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
              fontWeight: 700,
              fontSize: H * 0.028,
              color: "#ffffff",
              letterSpacing: 2,
              textTransform: "uppercase",
              textShadow: "0 2px 10px rgba(0,0,0,0.7)",
            }}
          >
            {label}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
