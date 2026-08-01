import React from "react";
import { Composition } from "remotion";
import { Hook, HookProps } from "./Hook";
import { ListCard, ListCardProps } from "./ListCard";
import { Takeover, TakeoverProps } from "./Takeover";
import { Stat, StatProps } from "./Stat";
import { LowerThird, LowerThirdProps } from "./LowerThird";
import { QuoteCard, QuoteCardProps } from "./QuoteCard";
import { Comparison, ComparisonProps } from "./Comparison";
import { Lottie, LottieProps } from "./Lottie";
import { SubscribePrompt, SubscribePromptProps } from "./SubscribePrompt";
import { Callout, CalloutProps } from "./Callout";
import { Counter, CounterProps } from "./Counter";
import { Emphasis, EmphasisProps } from "./Emphasis";
import { Steps, StepsProps } from "./Steps";
import { Checklist, ChecklistProps } from "./Checklist";
import { ProgressBar, ProgressBarProps } from "./ProgressBar";
import { KeyTakeaway, KeyTakeawayProps } from "./KeyTakeaway";
import { Definition, DefinitionProps } from "./Definition";
import { Warning, WarningProps } from "./Warning";
import { PriceCard, PriceCardProps } from "./PriceCard";
import { Testimonial, TestimonialProps } from "./Testimonial";
import { Countdown, CountdownProps } from "./Countdown";
import { Divider, DividerProps } from "./Divider";
import { QuestionCard, QuestionCardProps } from "./QuestionCard";
import { SharePrompt, SharePromptProps } from "./SharePrompt";
import { SwipeUp, SwipeUpProps } from "./SwipeUp";
import { CommentPrompt, CommentPromptProps } from "./CommentPrompt";
import { SaveThis, SaveThisProps } from "./SaveThis";

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
        id="Takeover"
        component={Takeover}
        durationInFrames={150}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ kicker: "REMEMBER THIS", title: "3 Ways To Breathe Better", items: ["Slow The Exhale", "Belly, Not Chest", "Four Counts In"], durationInFrames: 150, width: 1080, height: 1920, accent: "#5b7c3a" } as TakeoverProps}
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
      <Composition
        id="Lottie"
        component={Lottie}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ file: "sample.json", accent: "#FFD24A", key_color: "#ff00ff", loop: true, speed: 1, durationInFrames: 90, width: 1080, height: 1920 } as LottieProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="SubscribePrompt"
        component={SubscribePrompt}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ text: "SUBSCRIBE", handle: "@yourhandle", accent: "#FFD24A", durationInFrames: 90, width: 1080, height: 1920 } as SubscribePromptProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="Callout"
        component={Callout}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ text: "THIS CHANGES EVERYTHING", accent: "#FFD24A", durationInFrames: 90, width: 1080, height: 1920 } as CalloutProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="Counter"
        component={Counter}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ value: "10,000", label: "downloads in week one", accent: "#FFD24A", durationInFrames: 90, width: 1080, height: 1920 } as CounterProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="Emphasis"
        component={Emphasis}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ mode: "circle", cx: 0.5, cy: 0.5, accent: "#FFD24A", durationInFrames: 90, width: 1080, height: 1920 } as EmphasisProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="Steps"
        component={Steps}
        durationInFrames={150}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ title: "How it works", steps: ["Pick your niche", "Post daily", "Refine what works"], accent: "#FFD24A", durationInFrames: 150, width: 1080, height: 1920 } as StepsProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="Checklist"
        component={Checklist}
        durationInFrames={150}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ title: "Before you post", items: ["Strong hook", "One clear idea", "Clear call to action"], accent: "#FFD24A", durationInFrames: 150, width: 1080, height: 1920 } as ChecklistProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="ProgressBar"
        component={ProgressBar}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ label: "Completion", value: "72%", caption: "of viewers finish the video", accent: "#FFD24A", durationInFrames: 90, width: 1080, height: 1920 } as ProgressBarProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="KeyTakeaway"
        component={KeyTakeaway}
        durationInFrames={120}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ label: "Key Takeaway", text: "Consistency beats intensity every time.", accent: "#FFD24A", durationInFrames: 120, width: 1080, height: 1920 } as KeyTakeawayProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="Definition"
        component={Definition}
        durationInFrames={120}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ term: "Retention", definition: "The share of viewers still watching at a given second.", accent: "#FFD24A", durationInFrames: 120, width: 1080, height: 1920 } as DefinitionProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="Warning"
        component={Warning}
        durationInFrames={120}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ label: "Watch Out", text: "Never open with a slow intro.", accent: "#FFD24A", durationInFrames: 120, width: 1080, height: 1920 } as WarningProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="PriceCard"
        component={PriceCard}
        durationInFrames={120}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ label: "Today Only", price: "$49", was: "$99", cta: "Link in bio", accent: "#FFD24A", durationInFrames: 120, width: 1080, height: 1920 } as PriceCardProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="Testimonial"
        component={Testimonial}
        durationInFrames={150}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ quote: "This doubled my reach in a month.", name: "Sam Rivera", role: "Creator", stars: 5, accent: "#FFD24A", durationInFrames: 150, width: 1080, height: 1920 } as TestimonialProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="Countdown"
        component={Countdown}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ label: "Ends In", value: "24:00:00", accent: "#FFD24A", durationInFrames: 90, width: 1080, height: 1920 } as CountdownProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="Divider"
        component={Divider}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ kicker: "Part 2", text: "The System", accent: "#FFD24A", durationInFrames: 90, width: 1080, height: 1920 } as DividerProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="QuestionCard"
        component={QuestionCard}
        durationInFrames={120}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ question: "What is stopping you from starting?", accent: "#FFD24A", durationInFrames: 120, width: 1080, height: 1920 } as QuestionCardProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="SharePrompt"
        component={SharePrompt}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ text: "Like · Comment · Share", handle: "@yourhandle", accent: "#FFD24A", durationInFrames: 90, width: 1080, height: 1920 } as SharePromptProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="SwipeUp"
        component={SwipeUp}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ text: "Link in bio", accent: "#FFD24A", durationInFrames: 90, width: 1080, height: 1920 } as SwipeUpProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="CommentPrompt"
        component={CommentPrompt}
        durationInFrames={120}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ word: "YES", accent: "#FFD24A", durationInFrames: 120, width: 1080, height: 1920 } as CommentPromptProps}
        calculateMetadata={calcMeta}
      />
      <Composition
        id="SaveThis"
        component={SaveThis}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ text: "Save this", accent: "#FFD24A", durationInFrames: 90, width: 1080, height: 1920 } as SaveThisProps}
        calculateMetadata={calcMeta}
      />
    </>
  );
};
