import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  plugins: [svelte()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/health": "http://127.0.0.1:8000",
      "/detect": "http://127.0.0.1:8000",
      "/estimate-structure": "http://127.0.0.1:8000",
      "/session": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
