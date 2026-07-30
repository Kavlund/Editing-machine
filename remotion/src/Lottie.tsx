import React, { useEffect, useState } from "react";
import {
  AbsoluteFill,
  cancelRender,
  continueRender,
  delayRender,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Lottie as RemotionLottie } from "@remotion/lottie";
import { recolorLottie } from "./util";

export type LottieProps = {
  file: string;              // filename under remotion/public/lottie/
  accent: string;            // brand accent; recolours the sentinel-coloured element
  key_color?: string;        // the sentinel colour painted in Jitter (default magenta)
  loop?: boolean;
  speed?: number;
  durationInFrames: number;
  width: number;
  height: number;
};

// Renders a Jitter/Lottie export as a transparent, brand-recoloured overlay. It
// fetches the JSON (small; loaded by name, never inlined) and holds the first frame
// via delayRender until parsed, so headless Chromium never captures an empty frame.
export const Lottie: React.FC<LottieProps> = ({ file, accent, key_color, loop, speed }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const [data, setData] = useState<any>(null);
  const [handle] = useState(() => delayRender("lottie:" + file));

  useEffect(() => {
    fetch(staticFile("lottie/" + file))
      .then((r) => r.json())
      .then((j) => {
        setData(recolorLottie(j, accent, key_color || "#ff00ff"));
        continueRender(handle);
      })
      .catch((e) => cancelRender(e));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);

  const fade = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  if (!data) return null;
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: fade }}>
      <RemotionLottie
        animationData={data}
        loop={loop ?? true}
        playbackRate={speed ?? 1}
        style={{ width: "100%", height: "100%" }}
      />
    </AbsoluteFill>
  );
};
