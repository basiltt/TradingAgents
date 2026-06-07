/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import path from "path";

// Keep the dev proxy targeted at the SAME port the backend binds. start.sh / start.bat
// resolve TRADINGAGENTS_PORT (default 8877) for uvicorn; read it here too so a custom
// port doesn't silently break /api + /ws in dev. Loopback host: the proxy runs on the
// same machine as the backend.
const BACKEND_PORT = process.env.TRADINGAGENTS_PORT?.trim() || "8877";
const BACKEND_HTTP = `http://localhost:${BACKEND_PORT}`;
const BACKEND_WS = `ws://localhost:${BACKEND_PORT}`;

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // AI-CONTEXT: The service worker is intentionally self-destructing.
    // This is a live, real-time trading dashboard — it gets no meaningful
    // benefit from offline precaching, and the `autoUpdate` SW was a direct
    // cause of unexpected full-page reloads (on a new deploy, an autoUpdate SW
    // forces skipWaiting + clientsClaim and reloads every open tab). Setting
    // `selfDestroying: true` ships a SW (same filename) that unregisters itself
    // and deletes its caches on every device that already installed the old one,
    // cleanly removing it in production. Do NOT change the SW filename or other
    // workbox options while self-destroying — the plugin must reuse the old name
    // so existing clients pick up the replacement. To restore PWA behavior later,
    // remove `selfDestroying` (and reconsider `registerType`, see below).
    VitePWA({
      selfDestroying: true,
      registerType: "autoUpdate",
      injectRegister: "auto",
      devOptions: { enabled: false },
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,png,svg,woff2}"],
        navigateFallback: "index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/ws\//, /^\/neumorphism-preview/],
      },
      manifest: false,
    }),
  ],
  build: {
    chunkSizeWarningLimit: 250,
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, "index.html"),
        neumorphismPreview: path.resolve(__dirname, "neumorphism-preview.html"),
      },
      output: {
        manualChunks(id: string) {
          if (id.includes("node_modules/react-dom")) return "vendor-react";
          if (id.includes("node_modules/react/")) return "vendor-react";
          if (id.includes("node_modules/@tanstack/react-router")) return "vendor-router";
          if (id.includes("node_modules/@tanstack/react-query") || id.includes("node_modules/@tanstack/query-sync-storage-persister")) return "vendor-query";
          if (id.includes("node_modules/@reduxjs/toolkit") || id.includes("node_modules/react-redux")) return "vendor-redux";
          if (id.includes("node_modules/framer-motion")) return "vendor-motion";
          if (id.includes("node_modules/recharts") || id.includes("node_modules/d3-")) return "vendor-charts";
        },
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5177,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: BACKEND_HTTP,
        changeOrigin: true,
      },
      "/ws": {
        target: BACKEND_WS,
        ws: true,
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: "happy-dom",
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["e2e/**", "node_modules/**"],
    css: false,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/test/**",
        "src/**/__tests__/**",
        "src/routes/**",
        "src/main.tsx",
        "src/App.tsx",
        "src/design-system/**",
        "src/lib/motion.tsx",
        "src/lib/motion-constants.ts",
        "src/lib/use-animations.ts",
      ],
    },
  },
});
