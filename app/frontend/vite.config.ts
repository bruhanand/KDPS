import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served by the platform's process manager as `yarn start` on port 3000, behind
// the preview HTTPS proxy. `REACT_APP_*` env is exposed (the platform injects
// REACT_APP_BACKEND_URL) alongside Vite's own `VITE_*`.
export default defineConfig({
  plugins: [react()],
  envPrefix: ["VITE_", "REACT_APP_"],
  server: {
    host: true,
    port: 3000,
    strictPort: true,
    allowedHosts: true,
    hmr: { clientPort: 443 },
  },
});
