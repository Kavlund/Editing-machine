import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent } from "./util";

export type SwipeUpProps = {
  text?: string;   // defaults to "LINK IN BIO"
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// Upward chevrons that pulse up toward a pill label — "swipe up / link in bio".
export const SwipeUp: React.FC<SwipeUpProps> = ({ text, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;

  const enter = spring({ frame, fps, config: { damping: 12, stiffness: 150, mass: 0.7 } });
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: H * 0.14 }}>
      <div style={{ opacity: Math.min(enter, fade), display: "flex", flexDirection: "column", alignItems: "center", gap: H * 0.006 }}>
        {[0, 1, 2].map((i) => {
          const cycle = ((frame / fps) * 1.6 - i * 0.18) % 1;
          const up = interpolate(Math.max(0, cycle), [0, 1], [H * 0.012, -H * 0.006]);
          const op = interpolate(Math.max(0, cycle), [0, 0.5, 1], [0.2, 1, 0.2]);
          return (
            <svg key={i} width={H * 0.05} height={H * 0.03} viewBox="0 0 24 14" fill="none" stroke={ac} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" style={{ transform: `translateY(${up}px)`, opacity: op }}>
              <path d="M3 11l9-8 9 8" />
            </svg>
          );
        })}
        <div style={{ marginTop: H * 0.01, background: ac, color: "#0a0b10", fontFamily: font, fontWeight: 900, fontSize: H * 0.028, letterSpacing: 2, textTransform: "uppercase", padding: `${H * 0.014}px ${H * 0.034}px`, borderRadius: H * 0.5, boxShadow: `0 ${H * 0.01}px ${H * 0.028}px rgba(0,0,0,0.45)` }}>{text || "Link in bio"}</div>
      </div>
    </AbsoluteFill>
  );
};
