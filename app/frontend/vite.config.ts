import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

import { PWA_OPTIONS } from "./src/pwa/config";

// Served by the platform's process manager as `yarn start` on port 3000, behind
// the preview HTTPS proxy. `REACT_APP_*` env is exposed (the platform injects
// REACT_APP_BACKEND_URL) alongside Vite's own `VITE_*`.
//
// HMR has two shapes. Behind the Emergent preview proxy the browser reaches the
// dev server over HTTPS on 443, so the HMR socket must be told that port. On a
// dev machine (scripts/dev.sh sets VITE_LOCAL_DEV=1) the browser talks to
// http://localhost:3000 directly, and clientPort 443 would make it dial
// wss://localhost:443 — nothing listens there, so hot reload silently dies.
export default defineConfig({
  // The installed counter (#189). Everything it does - and the one thing it must
  // never do, which is cache an API response - lives in `src/pwa/config.ts`.
  plugins: [react(), VitePWA(PWA_OPTIONS)],
  envPrefix: ["VITE_", "REACT_APP_"],
  server: {
    host: true,
    port: 3000,
    strictPort: true,
    allowedHosts: true,
    hmr: process.env.VITE_LOCAL_DEV === "1" ? true : { clientPort: 443 },
    // This container's inotify watch limit (/proc/sys/fs/inotify/max_user_watches)
    // is read-only and cannot be raised, so native fs events run out of watches
    // (ENOSPC) and crash the dev server under this repo's file count. Polling
    // avoids inotify entirely.
    watch: { usePolling: true, interval: 300 },
  },
});
