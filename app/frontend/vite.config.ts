import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

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
  plugins: [react()],
  envPrefix: ["VITE_", "REACT_APP_"],
  server: {
    host: true,
    port: 3000,
    strictPort: true,
    allowedHosts: true,
    hmr: process.env.VITE_LOCAL_DEV === "1" ? true : { clientPort: 443 },
  },
});
