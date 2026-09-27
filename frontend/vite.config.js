import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// The dataset lives outside this folder (../data/processed). Vite needs
// explicit permission to read above the project root in dev.
const repoRoot = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    fs: { allow: [repoRoot] },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // The 3D view's deck.gl chunk (~1 MB) is lazy-loaded on first use, so it
    // never blocks the initial page; don't warn about it.
    chunkSizeWarningLimit: 1100,
  },
});
