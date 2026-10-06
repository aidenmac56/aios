import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI app serves ../aios/web_dist (index.html + assets/) and the JSON API under /api.
export default defineConfig({
  base: "/",
  plugins: [react()],
  build: {
    outDir: "../aios/web_dist",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8787", changeOrigin: false },
    },
  },
});
