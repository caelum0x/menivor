"use client";

import type { FreeToolWidget as WidgetKey } from "@/lib/seo/free-tools/catalog";
import { AiTextTool } from "./AiTextTool";
import { SpeechToText, VoiceoverTool } from "./BrowserAiTools";
import { AspectRatioCalculator, BitrateCalculator, ScriptLengthCalculator } from "./Calculators";
import { SrtVttConverter, SubtitleShifter } from "./SubtitleTools";

const PLACEHOLDER = "Example: a cold brew coffee kit for busy parents who want cafe coffee at home";

export function FreeToolWidget({ widget }: { readonly widget: WidgetKey }) {
  switch (widget) {
    case "hooks":
      return <AiTextTool kind="hooks" placeholder={PLACEHOLDER} />;
    case "script":
      return <AiTextTool kind="script" placeholder={PLACEHOLDER} />;
    case "hashtags":
      return <AiTextTool kind="hashtags" placeholder="Example: easy 15-minute high-protein breakfast ideas" />;
    case "titles":
      return <AiTextTool kind="titles" placeholder="Example: how I edit a week of short videos in one afternoon" defaultPlatform="youtube" />;
    case "captions":
      return <AiTextTool kind="captions" placeholder={PLACEHOLDER} />;
    case "ideas":
      return <AiTextTool kind="ideas" placeholder="Example: a small bakery that wants more foot traffic on weekends" />;
    case "script-shorts":
      return <AiTextTool kind="script" placeholder={PLACEHOLDER} defaultPlatform="shorts" />;
    case "subtitles":
      return <SpeechToText mode="subtitles" />;
    case "transcript":
      return <SpeechToText mode="transcript" />;
    case "voiceover":
      return <VoiceoverTool />;
    case "srt-vtt":
      return <SrtVttConverter />;
    case "shifter":
      return <SubtitleShifter />;
    case "aspect":
      return <AspectRatioCalculator />;
    case "bitrate":
      return <BitrateCalculator />;
    case "script-length":
      return <ScriptLengthCalculator />;
  }
}
