import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Vite config for the ReelForge Desktop renderer.
 *
 * `base: "./"` makes the built asset URLs relative so Electron can load the
 * bundle over `file://` from the packaged `dist/` directory. The dev server is
 * pinned to a fixed port so the Electron main process can reliably attach to it
 * in development (`app.isPackaged === false`).
 */
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
    sourcemap: true,
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});
