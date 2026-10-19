/**
 * In-browser model workers for the free tools. Each worker is a module worker
 * built from a Blob so the multi-megabyte runtimes (Transformers.js, Kokoro)
 * load from jsDelivr only when a visitor actually runs a tool; nothing is
 * bundled into the Next.js build and nothing the visitor picks is uploaded.
 *
 * Pinned versions: @huggingface/transformers 3.8.1 (Apache-2.0),
 * kokoro-js 1.2.1 (Apache-2.0). Models come from the Hugging Face Hub.
 */

export const TRANSFORMERS_URL = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1/dist/transformers.min.js";
export const KOKORO_URL = "https://cdn.jsdelivr.net/npm/kokoro-js@1.2.1/dist/kokoro.web.js";
export const WHISPER_MODEL = "onnx-community/whisper-base";
/** English-only checkpoint: noticeably more accurate on English speech. */
export const WHISPER_EN_MODEL = "onnx-community/whisper-base.en";
export const KOKORO_MODEL = "onnx-community/Kokoro-82M-v1.0-ONNX";

const WHISPER_SOURCE = `
import { pipeline, env } from "${TRANSFORMERS_URL}";
env.allowLocalModels = false;
const pipes = new Map();
const progress = (p) => {
  if (p && p.status === "progress" && typeof p.progress === "number") {
    self.postMessage({ type: "progress", file: p.file, progress: p.progress });
  }
};
self.onmessage = async (event) => {
  const { audio, language } = event.data;
  try {
    const english = language === "english";
    const model = english ? "${WHISPER_EN_MODEL}" : "${WHISPER_MODEL}";
    if (!pipes.has(model)) {
      self.postMessage({ type: "status", message: "Downloading the speech model (first run only)..." });
      pipes.set(model, await pipeline("automatic-speech-recognition", model, {
        dtype: { encoder_model: "fp32", decoder_model_merged: "q8" },
        device: "wasm",
        progress_callback: progress,
      }));
    }
    const asr = pipes.get(model);
    self.postMessage({ type: "status", message: "Transcribing on your device..." });
    const options = { chunk_length_s: 30, stride_length_s: 5, return_timestamps: true };
    const out = await asr(audio, english ? options : { ...options, language, task: "transcribe" });
    const chunks = (out.chunks || []).map((c) => ({
      text: c.text,
      start: Array.isArray(c.timestamp) ? (c.timestamp[0] ?? 0) : 0,
      end: Array.isArray(c.timestamp) ? c.timestamp[1] : null,
    }));
    self.postMessage({ type: "done", text: out.text || "", chunks });
  } catch (error) {
    self.postMessage({ type: "error", message: String((error && error.message) || error) });
  }
};
`;

const KOKORO_SOURCE = `
import { KokoroTTS } from "${KOKORO_URL}";
let tts = null;
self.onmessage = async (event) => {
  const { text, voice, speed } = event.data;
  try {
    if (!tts) {
      self.postMessage({ type: "status", message: "Downloading the voice model (first run only)..." });
      tts = await KokoroTTS.from_pretrained("${KOKORO_MODEL}", {
        dtype: "q8",
        device: "wasm",
        progress_callback: (p) => {
          if (p && p.status === "progress" && typeof p.progress === "number") {
            self.postMessage({ type: "progress", file: p.file, progress: p.progress });
          }
        },
      });
    }
    self.postMessage({ type: "status", message: "Generating the voiceover on your device..." });
    const audio = await tts.generate(text, { voice, speed });
    self.postMessage({ type: "done", blob: audio.toBlob() });
  } catch (error) {
    self.postMessage({ type: "error", message: String((error && error.message) || error) });
  }
};
`;

function createModuleWorker(source: string): Worker {
  const url = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
  // The URL is kept alive: revoking it before the worker script is fetched
  // breaks module workers in some browsers. One small blob per page view.
  return new Worker(url, { type: "module" });
}

export function createWhisperWorker(): Worker {
  return createModuleWorker(WHISPER_SOURCE);
}

export function createKokoroWorker(): Worker {
  return createModuleWorker(KOKORO_SOURCE);
}

export const MAX_MEDIA_BYTES = 200 * 1024 * 1024;
export const MAX_MEDIA_SECONDS = 600;
const SAMPLE_RATE = 16_000;

/** Decode any browser-playable audio/video file to 16 kHz mono PCM. */
export async function decodeToMono16k(file: File): Promise<Float32Array> {
  const buffer = await file.arrayBuffer();
  const AudioCtx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const context = new AudioCtx({ sampleRate: SAMPLE_RATE });
  try {
    const decoded = await context.decodeAudioData(buffer);
    if (decoded.duration > MAX_MEDIA_SECONDS) {
      throw new Error(`That clip is ${Math.round(decoded.duration / 60)} minutes long. The free tool handles up to 10 minutes.`);
    }
    if (decoded.numberOfChannels === 1) return decoded.getChannelData(0);
    const left = decoded.getChannelData(0);
    const right = decoded.getChannelData(1);
    return Float32Array.from(left, (sample, index) => (sample + (right[index] ?? 0)) / 2);
  } finally {
    void context.close();
  }
}
