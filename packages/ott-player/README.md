# @menivor/ott-player

Framework-free core of the Menivor OTT web player (Wave P PM2.5, MV4): HLS attach (native, else
hls.js, Apache-2.0), one sound at a time, and playback-token refresh before expiry. The React
wrapper lives in `apps/web/src/features/ott-player`. UI controls come from media-chrome (MIT) in
the web app. Copy says "Protected streaming" only where access tier 1 is live, never "DRM".
