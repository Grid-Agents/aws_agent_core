import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI proxy (grid-local-api) serves the review API, cited figures, and
// the original submission PDFs. Forward all three to it during local dev.
const API = process.env.GRID_API_URL || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api": { target: API, changeOrigin: true },
      "/artifacts": { target: API, changeOrigin: true },
      "/review-pdfs": { target: API, changeOrigin: true },
    },
  },
});
