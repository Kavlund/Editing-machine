import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent, withAlpha } from "./util";

export type TestimonialProps = {
  quote?: string;
  name?: string;
  role?: string;
  stars?: number;   // 0-5
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// A social-proof card: quote, attribution, and a row of star ratings that pop in,
// stars filled in the client's brand accent.
export const Testimonial: React.FC<TestimonialProps> = ({ quote, name, role, stars, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;
  const n = Math.max(0, Math.min(5, Math.round(stars == null ? 5 : stars)));

  const enter = spring({ frame, fps, config: { damping: 13, stiffness: 160, mass: 0.7 } });
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: `0 ${H * 0.06}px` }}>
      <div style={{ opacity: Math.min(enter, fade), width: "100%", maxWidth: H * 0.64, background: withAlpha("#0c0e15", 0.93), borderRadius: H * 0.018, padding: `${H * 0.03}px ${H * 0.032}px`, transform: `translateY(${interpolate(enter, [0, 1], [H * 0.03, 0])}px)`, boxShadow: `0 ${H * 0.01}px ${H * 0.03}px rgba(0,0,0,0.45)` }}>
        <div style={{ display: "flex", gap: H * 0.006, marginBottom: H * 0.016 }}>
          {Array.from({ length: 5 }).map((_, i) => {
            const s = spring({ frame: frame - 6 - i * 4, fps, config: { damping: 11, stiffness: 170, mass: 0.5 } });
            const on = i < n;
            return (
              <svg key={i} width={H * 0.04} height={H * 0.04} viewBox="0 0 24 24" fill={on ? ac : "rgba(255,255,255,0.18)"} style={{ transform: `scale(${on ? s : 1})` }}>
                <path d="M12 2l2.9 6.3 6.9.7-5.1 4.6 1.4 6.8L12 17.8 5.9 21.4l1.4-6.8L2.2 9l6.9-.7z" />
              </svg>
            );
          })}
        </div>
        <div style={{ fontFamily: font, fontWeight: 800, fontSize: H * 0.04, lineHeight: 1.2, color: "#fff" }}>&ldquo;{quote || "This completely changed how I work."}&rdquo;</div>
        {(name || role) ? (
          <div style={{ marginTop: H * 0.016, fontFamily: font, fontWeight: 700, fontSize: H * 0.026, color: ac }}>
            {name || ""}{role ? <span style={{ color: "rgba(255,255,255,0.7)" }}>{name ? ",  " : ""}{role}</span> : null}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
