import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY } from "./font";
import { readableAccent, withAlpha } from "./util";

export type PriceCardProps = {
  price?: string;   // "$49"
  was?: string;     // "$99" (struck through)
  label?: string;   // "TODAY ONLY"
  cta?: string;     // "Link in bio"
  accent: string;
  accent2?: string;
  durationInFrames: number;
  width: number;
  height: number;
};

// An offer / price card: big accent price, optional struck "was", label + CTA.
export const PriceCard: React.FC<PriceCardProps> = ({ price, was, label, cta, accent, height }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ac = readableAccent(accent);
  const H = height;
  const font = `${FONT_FAMILY}, 'Arial Black', sans-serif`;

  const enter = spring({ frame, fps, config: { damping: 11, stiffness: 160, mass: 0.7 } });
  const priceIn = spring({ frame: frame - 6, fps, config: { damping: 10, stiffness: 150, mass: 0.7 } });
  const fade = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <div style={{ opacity: Math.min(enter, fade), transform: `scale(${interpolate(enter, [0, 1], [0.85, 1])})`, background: withAlpha("#0c0e15", 0.94), borderRadius: H * 0.02, padding: `${H * 0.03}px ${H * 0.05}px`, textAlign: "center", border: `${H * 0.003}px solid ${withAlpha(ac, 0.5)}`, boxShadow: `0 ${H * 0.012}px ${H * 0.035}px rgba(0,0,0,0.5)` }}>
        {label ? (
          <div style={{ display: "inline-block", background: ac, color: "#0a0b10", fontFamily: font, fontWeight: 900, fontSize: H * 0.024, letterSpacing: 2, textTransform: "uppercase", padding: `${H * 0.007}px ${H * 0.016}px`, borderRadius: 999, marginBottom: H * 0.016 }}>{label}</div>
        ) : null}
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "center", gap: H * 0.02 }}>
          {was ? <span style={{ fontFamily: font, fontWeight: 700, fontSize: H * 0.045, color: "rgba(255,255,255,0.55)", textDecoration: "line-through" }}>{was}</span> : null}
          <span style={{ fontFamily: font, fontWeight: 900, fontSize: H * 0.11, color: ac, lineHeight: 1, transform: `scale(${interpolate(priceIn, [0, 1], [0.7, 1])})`, textShadow: "0 4px 16px rgba(0,0,0,0.5)" }}>{price || "$49"}</span>
        </div>
        {cta ? (
          <div style={{ marginTop: H * 0.016, fontFamily: font, fontWeight: 800, fontSize: H * 0.028, color: "#fff", letterSpacing: 1 }}>{cta}</div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
