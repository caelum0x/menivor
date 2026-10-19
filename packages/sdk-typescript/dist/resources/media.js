const TERMINAL = new Set(["completed", "failed"]);
/** Is a video job in a terminal state? */
export function isTerminalStatus(status) {
    return TERMINAL.has(status);
}
/** Unified image + video generation over one key + one balance. */
export class MediaResource {
    request;
    constructor(request) {
        this.request = request;
    }
    /** List image + video models (optionally filtered by modality). */
    listModels(modality) {
        return this.request("GET", "/media/models", {
            query: modality === undefined ? {} : { modality },
        });
    }
    /** Generate an image synchronously → `{ url }`. */
    createImage(body) {
        return this.request("POST", "/media/images", { body });
    }
    /** Submit a video job (poll it with {@link getVideo} or {@link waitForVideo}). */
    createVideo(body) {
        return this.request("POST", "/media/videos", { body });
    }
    /** Poll a video job once. */
    getVideo(jobId) {
        return this.request("GET", `/media/videos/${encodeURIComponent(jobId)}`);
    }
    /** Submit a music/audio job (poll it with {@link getAudio}). */
    createAudio(body) {
        return this.request("POST", "/media/audio", { body });
    }
    /** Poll an audio job once. */
    getAudio(jobId) {
        return this.request("GET", `/media/audio/${encodeURIComponent(jobId)}`);
    }
    /** Submit a video and poll until it reaches a terminal status. */
    async waitForVideo(body, options = {}) {
        const intervalMs = options.intervalMs ?? 3000;
        const maxAttempts = options.maxAttempts ?? 200;
        const sleep = options.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
        let job = await this.createVideo(body);
        let attempts = 0;
        while (!isTerminalStatus(job.status)) {
            if (++attempts > maxAttempts) {
                throw new Error(`waitForVideo: job ${job.id} did not finish in ${maxAttempts} polls`);
            }
            await sleep(intervalMs);
            job = await this.getVideo(job.id);
        }
        return job;
    }
    /** Spendable credits + lifetime gateway spend. */
    credits() {
        return this.request("GET", "/media/credits");
    }
    /** Gateway spend + job counts grouped by model. */
    usage(limit) {
        return this.request("GET", "/media/usage", {
            query: limit === undefined ? {} : { limit },
        });
    }
    /** Per-generation cost/status detail (OpenRouter `/generation?id=`). */
    generation(jobId) {
        return this.request("GET", `/media/generation/${encodeURIComponent(jobId)}`);
    }
}
/** Integer-microdollar → "$0.084" style display (1 USD = 1_000_000 micros). */
export function formatUsdMicros(micros) {
    const usd = (micros || 0) / 1_000_000;
    const digits = usd !== 0 && Math.abs(usd) < 0.1 ? 3 : 2;
    return `$${usd.toFixed(digits)}`;
}
