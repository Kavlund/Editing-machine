import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent } from "./util";

export type SubscribePromptProps = {
  text?: string;        // e.g. "SUBSCRIBE" or "FOLLOW"
  handle?: string;      // e.g. "@yourhandle"
  accent: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// An animated subscribe / follow button that pops in with a bounce, gives a
// finger-tap cue, and rides a subtle attention pulse. Brand-accent fill.
export const SubscribePrompt: React.FC<SubscribePromptProps> = ({ text, handle, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;

  const enter = spring({ frame, fps, config: { damping: 10, stiffness: 150, mass: 0.7 } });
  const scale = interpolate(enter, [0, 1], [0.55, 1]);
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const pulse = 1 + 0.035 * Math.sin((frame / fps) * 6.5);
  // finger tap: drops in and taps twice
  const tapIn = spring({ frame: frame - 8, fps, config: { damping: 12, stiffness: 160, mass: 0.6 } });
  const tap = Math.max(0, Math.sin((frame / fps) * 7)) * 0.5;
  const label = (text || "SUBSCRIBE").toUpperCase();

  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center", paddingTop: H * 0.13 }}>
      <div
        style={{
          transform: `scale(${scale * pulse})`,
          opacity: Math.min(enter, fade),
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: H * 0.014,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: H * 0.016,
            background: ac,
            borderRadius: H * 0.5,
            padding: `${H * 0.016}px ${H * 0.04}px`,
            boxShadow: `0 ${H * 0.012}px ${H * 0.03}px rgba(0,0,0,0.45)`,
          }}
        >
          <svg width={H * 0.036} height={H * 0.036} viewBox="0 0 24 24" fill="#0a0b10">
            <path d="M12 2a6 6 0 0 0-6 6v3.6L4.3 15c-.5.9.1 2 1.2 2h13c1.1 0 1.7-1.1 1.2-2L18 11.6V8a6 6 0 0 0-6-6zM12 22a2.6 2.6 0 0 0 2.6-2.6H9.4A2.6 2.6 0 0 0 12 22z" />
          </svg>
          <span
            style={{
              fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
              fontWeight: 800,
              fontSize: H * 0.03,
              color: "#0a0b10",
              letterSpacing: 1,
            }}
          >
            {label}
          </span>
        </div>
        {handle ? (
          <span
            style={{
              fontFamily: `${FONT_FAMILY}, 'Arial Black', sans-serif`,
              fontWeight: 700,
              fontSize: H * 0.02,
              color: "#ffffff",
              textShadow: "0 2px 8px rgba(0,0,0,0.7)",
            }}
          >
            {handle}
          </span>
        ) : null}
        {/* finger-tap cue */}
        <div
          style={{
            transform: `translateY(${interpolate(tapIn, [0, 1], [H * 0.05, tap * H * 0.012])}px) rotate(-18deg)`,
            opacity: interpolate(tapIn, [0, 1], [0, 0.95]),
            marginTop: -H * 0.02,
          }}
        >
          <svg width={H * 0.055} height={H * 0.055} viewBox="0 0 24 24" fill="#ffffff" style={{ filter: "drop-shadow(0 3px 6px rgba(0,0,0,0.5))" }}>
            <path d="M9 11V6a2 2 0 1 1 4 0v5h1V8a2 2 0 1 1 4 0v6a6 6 0 0 1-6 6h-1.5a4 4 0 0 1-3.4-1.9l-2.4-4c-.5-.9-.2-2 .7-2.5.8-.4 1.7-.2 2.2.5L9 13V11z" />
          </svg>
        </div>
      </div>
    </AbsoluteFill>
  );
};
