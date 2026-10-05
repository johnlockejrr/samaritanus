import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only proxy: keeps the app same-origin in dev exactly like the container does,
// so nothing has to hardcode the API host.
const API_TARGET = process.env.VITE_DEV_API_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 500,
  },
});
