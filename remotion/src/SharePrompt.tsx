import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent, withAlpha } from "./util";

export type SharePromptProps = {
  text?: string;    // defaults to "LIKE • COMMENT • SHARE"
  handle?: string;
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A like / comment / share cue: three icons pop in on an accent bar, each with a
// tap bounce. For a generic engagement nudge (not a specific subscribe ask).
export const SharePrompt: React.FC<SharePromptProps> = ({ text, handle, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;

  const enter = spring({ frame, fps, config: { damping: 11, stiffness: 150, mass: 0.7 } });
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const icons = [
    "M12 21s-7.5-4.6-10-9.3C.4 8.4 2.2 5 5.5 5c2 0 3.3 1.1 4.1 2.3C10.4 6.1 11.7 5 13.7 5 17 5 18.9 8.4 17.3 11.7 14.8 16.4 12 21 12 21z",
    "M4 4h16v12H8l-4 4z",
    "M14 9V5l7 7-7 7v-4H4a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1z",
  ];

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: H * 0.17 }}>
      <div style={{ opacity: Math.min(enter, fade), transform: `scale(${interpolate(enter, [0, 1], [0.7, 1])})`, display: "flex", flexDirection: "column", alignItems: "center", gap: H * 0.012 }}>
        <div style={{ display: "flex", alignItems: "center", gap: H * 0.03, background: ac, borderRadius: H * 0.5, padding: `${H * 0.016}px ${H * 0.04}px`, boxShadow: `0 ${H * 0.012}px ${H * 0.03}px rgba(0,0,0,0.45)` }}>
          {icons.map((d, i) => {
            const s = spring({ frame: frame - 8 - i * 6, fps, config: { damping: 9, stiffness: 180, mass: 0.5 } });
            return (
              <svg key={i} width={H * 0.045} height={H * 0.045} viewBox="0 0 24 24" fill="#0a0b10" style={{ transform: `scale(${interpolate(s, [0, 1], [0, 1])})` }}>
                <path d={d} />
              </svg>
            );
          })}
        </div>
        <div style={{ fontFamily: font, fontWeight: 800, fontSize: H * 0.024, color: "#fff", letterSpacing: 2, textTransform: "uppercase", textShadow: "0 2px 8px rgba(0,0,0,0.7)" }}>{text || "Like · Comment · Share"}</div>
        {handle ? <div style={{ fontFamily: font, fontWeight: 700, fontSize: H * 0.02, color: withAlpha(ac, 0.95), textShadow: "0 2px 8px rgba(0,0,0,0.7)" }}>{handle}</div> : null}
      </div>
    </AbsoluteFill>
  );
};
