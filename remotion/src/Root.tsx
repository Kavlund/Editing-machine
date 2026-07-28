import React from "react";
import { Composition } from "remotion";
import { Hook, HookProps } from "./Hook";
import { ListCard, ListCardProps } from "./ListCard";
import { Stat, StatProps } from "./Stat";
import { LowerThird, LowerThirdProps } from "./LowerThird";
import { QuoteCard, QuoteCardProps } from "./QuoteCard";
import { Comparison, ComparisonProps } from "./Comparison";

// Every template's duration + frame size are dynamic (from props), so one template
// serves any video length and aspect ratio. The pipeline passes durationInFrames,
// width, height, accent alongside the content props.
const calcMeta = ({
  props,
}: {
  props: { durationInFrames: number; width: number; height: number };
}) => ({
  durationInFrames: Math.max(30, Math.round(props.durationInFrames)),
  width: Math.round(props.width),
  height: Math.round(props.height),
  fps: 30,
});

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Hook"
        component={Hook}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ text: "STOP SCROLLING", durationInFrames: 90, width: 1080, height: 1920, accent: "#ffffff" } as HookProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="ListCard"
        component={ListCard}
        durationInFrames={150}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ title: "3 Ways To Win", items: ["Show Up Daily", "Serve First", "Stay Consistent"], durationInFrames: 150, width: 1080, height: 1920, accent: "#FFD24A" } as ListCardProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="Stat"
        component={Stat}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ value: "90%", label: "of viewers drop off in the first 3 seconds", durationInFrames: 90, width: 1080, height: 1920, accent: "#FFD84D" } as StatProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="LowerThird"
        component={LowerThird}
        durationInFrames={120}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ name: "Jane Doe", subtitle: "Founder & CEO", durationInFrames: 120, width: 1080, height: 1920, accent: "#FFB800" } as LowerThirdProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="QuoteCard"
        component={QuoteCard}
        durationInFrames={150}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ quote: "The best time to start was yesterday. The next best time is right now.", attribution: "James Clear", durationInFrames: 150, width: 1080, height: 1920, accent: "#FFD24A" } as QuoteCardProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="Comparison"
        component={Comparison}
        durationInFrames={150}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ leftLabel: "MYTH", leftText: "More content means more growth", rightLabel: "TRUTH", rightText: "One clear message beats ten noisy ones", durationInFrames: 150, width: 1080, height: 1920, accent: "#4ADE80" } as ComparisonProps}
        calculateMetadata={calcMeta}
      />
    </>
  );
};
