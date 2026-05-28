/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import path from "path";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
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
        target: "http://localhost:8877",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8877",
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
