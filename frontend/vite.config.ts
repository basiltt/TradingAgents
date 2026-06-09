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

// AI-CONTEXT: SECURITY — Content-Security-Policy injected at BUILD time only.
// This app intentionally stores user-owned LLM API keys client-side
// (see src/lib/endpoints.ts); its threat model concedes XSS would expose them, so a
// CSP that blocks injected scripts and cross-origin exfiltration meaningfully shrinks
// the blast radius. It is applied via transformIndexHtml gated on `apply: "build"` so
// the dev server's HMR (which needs inline scripts / eval that script-src 'self'
// would block) is unaffected. frame-ancestors / HSTS must still be set as RESPONSE
// HEADERS by the server — a meta tag cannot enforce them.
const CSP = [
  "default-src 'self'",
  "script-src 'self'", // no inline scripts ship in the prod build (verified)
  "style-src 'self' 'unsafe-inline'", // design system uses inline style props
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self' ws: wss:", // all API/WS traffic is same-origin
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'self'",
].join("; ");

const cspPlugin = {
  name: "inject-csp-meta",
  apply: "build" as const,
  transformIndexHtml(html: string) {
    return html.replace(
      "<head>",
      `<head>\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`,
    );
  },
};

export default defineConfig({
  plugins: [
    cspPlugin,
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
