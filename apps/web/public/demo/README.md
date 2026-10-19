# Product demo video

Drop the real Menivor demo here to light up the "See it in action" section on
the marketing landing (`components/marketing/DemoVideo.tsx`).

## To publish the demo

1. Add the video file at:

   ```
   apps/web/public/demo/menivor-demo.mp4
   ```

   (optionally a poster frame at `apps/web/public/demo/menivor-demo-poster.jpg`)

2. Point the section at it. Either:

   - Set the constant in `components/marketing/DemoVideo.tsx`:
     ```ts
     export const MENIVOR_DEMO_VIDEO_URL = "/demo/menivor-demo.mp4";
     export const MENIVOR_DEMO_POSTER_URL = "/demo/menivor-demo-poster.jpg";
     ```
   - **or** set build-time env vars (take precedence, good for R2/CDN hosting):
     ```
     NEXT_PUBLIC_MENIVOR_DEMO_VIDEO_URL=https://cdn.menivor.com/menivor-demo.mp4
     NEXT_PUBLIC_MENIVOR_DEMO_POSTER_URL=https://cdn.menivor.com/menivor-demo-poster.jpg
     ```

3. Rebuild + deploy. Until a source is set, the section renders a graceful
   "Demo coming soon" placeholder (never a broken video element).

Recommended encoding: H.264/AAC MP4, 16:9, 1080p, ~60s, web-optimized
(`-movflags +faststart`).
