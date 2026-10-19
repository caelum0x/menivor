/**
 * TS≡Python client parity — the compiled TS Publisher clients must emit exactly
 * the request shapes (and normalized results) pinned in the golden, which the
 * Python clients reproduce in `test/test_clients.py`. Records requests via an
 * injected fake http (the network seam) — no network, no tokens persisted.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const m = await import(join(here, "..", "dist", "index.js"));
const golden = JSON.parse(
  readFileSync(join(here, "fixtures", "golden", "clients.json"), "utf8"),
);

function canon(v) {
  if (Array.isArray(v)) return `[${v.map(canon).join(",")}]`;
  if (v && typeof v === "object")
    return `{${Object.keys(v)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canon(v[k])}`)
      .join(",")}}`;
  return JSON.stringify(v);
}

let f = 0,
  n = 0;
const ck = (label, got, want) => {
  n++;
  if (canon(got) !== canon(want)) {
    f++;
    console.error(`MISMATCH ${label}\n TS ${canon(got)}\n GD ${canon(want)}`);
  }
};

// Fake http that records the request shape and returns queued canned responses.
function recorder(responses) {
  const calls = [];
  const queue = [...responses];
  const fn = async (url, opts = {}) => {
    calls.push({
      method: opts.method ?? "GET",
      url,
      token: opts.token ?? null,
      headers: opts.headers ?? null,
      body: opts.body ?? null,
    });
    return queue.shift();
  };
  return { fn, calls };
}

const REQ = {
  videoUrl: "https://cdn.reelforge.test/r/abc123.mp4",
  caption: "Ship your Shorts everywhere",
  aspect: "9:16",
  durationS: 28,
};

const pub = (r) => ({ platform: r.platform, post_id: r.postId, url: r.url });
const refresh = (r) => ({ access_token: r.accessToken, expires_in: r.expiresIn });
const analytics = (r) => ({
  platform: r.platform,
  views: r.views,
  watch_time_s: r.watch_time_s,
  retention_pct: r.retention_pct,
});

async function runPublish() {
  let rec = recorder([{ data: { publish_id: "vpub_1" } }]);
  let res = await new m.TikTokPublisher(rec.fn).publish(REQ, "tt_access");
  ck("publish.tiktok.req", rec.calls, golden.publish.tiktok.requests);
  ck("publish.tiktok.res", pub(res), golden.publish.tiktok.result);

  rec = recorder([{ id: "cont_1" }, { id: "ig_media_1" }]);
  res = await new m.InstagramPublisher(rec.fn).publish(REQ, "17841400000000000:ig_access");
  ck("publish.instagram.req", rec.calls, golden.publish.instagram.requests);
  ck("publish.instagram.res", pub(res), golden.publish.instagram.result);

  rec = recorder([{ id: "yt_vid_1" }]);
  res = await new m.YouTubePublisher(rec.fn).publish(REQ, "yt_access");
  ck("publish.youtube.req", rec.calls, golden.publish.youtube.requests);
  ck("publish.youtube.res", pub(res), golden.publish.youtube.result);

  rec = recorder([{ data: { id: "tweet_1" } }]);
  res = await new m.XPublisher(rec.fn).publish(REQ, "media_55:x_access");
  ck("publish.x.req", rec.calls, golden.publish.x.requests);
  ck("publish.x.res", pub(res), golden.publish.x.result);
}

async function runRefresh() {
  const cases = [
    ["tiktok", m.TikTokPublisher, "tt_refresh", { access_token: "tt_new", expires_in: 86400 }],
    ["instagram", m.InstagramPublisher, "ig_longlived", { access_token: "ig_new", expires_in: 5184000 }],
    ["youtube", m.YouTubePublisher, "yt_refresh", { access_token: "yt_new", expires_in: 3599 }],
    ["x", m.XPublisher, "x_refresh", { access_token: "x_new", expires_in: 7200 }],
  ];
  for (const [name, Cls, tok, resp] of cases) {
    const rec = recorder([resp]);
    const res = await new Cls(rec.fn).refresh(tok);
    ck(`refresh.${name}.req`, rec.calls, golden.refresh[name].requests);
    ck(`refresh.${name}.res`, refresh(res), golden.refresh[name].result);
  }
}

async function runAnalytics() {
  let rec = recorder([{ data: { videos: [{ view_count: 1234, average_watch_time: 12 }] } }]);
  let res = await new m.TikTokPublisher(rec.fn).fetchAnalytics("vpub_1", "tt_access");
  ck("analytics.tiktok.req", rec.calls, golden.analytics.tiktok.requests);
  ck("analytics.tiktok.res", analytics(res), golden.analytics.tiktok.result);

  rec = recorder([
    { data: [
      { name: "plays", values: [{ value: 999 }] },
      { name: "reach", values: [{ value: 800 }] },
    ] },
  ]);
  res = await new m.InstagramPublisher(rec.fn).fetchAnalytics("ig_media_1", "17841400000000000:ig_access");
  ck("analytics.instagram.req", rec.calls, golden.analytics.instagram.requests);
  ck("analytics.instagram.res", analytics(res), golden.analytics.instagram.result);

  rec = recorder([{ items: [{ statistics: { viewCount: "4567" } }] }]);
  res = await new m.YouTubePublisher(rec.fn).fetchAnalytics("yt_vid_1", "yt_access");
  ck("analytics.youtube.req", rec.calls, golden.analytics.youtube.requests);
  ck("analytics.youtube.res", analytics(res), golden.analytics.youtube.result);

  rec = recorder([{ data: { public_metrics: { impression_count: 321 } } }]);
  res = await new m.XPublisher(rec.fn).fetchAnalytics("tweet_1", "media_55:x_access");
  ck("analytics.x.req", rec.calls, golden.analytics.x.requests);
  ck("analytics.x.res", analytics(res), golden.analytics.x.result);
}

await runPublish();
await runRefresh();
await runAnalytics();
ck("x_post_cost_micros", m.X_POST_COST_MICROS, golden.x_post_cost_micros);

if (f) {
  console.error(`\npublishing-connectors client parity FAILED: ${f}/${n}`);
  process.exit(1);
}
console.log(`publishing-connectors TS≡Python client parity OK (${n} cases)`);
