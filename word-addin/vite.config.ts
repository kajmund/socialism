import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import react from "@vitejs/plugin-react"
import { defineConfig, type ServerOptions } from "vite"

const rootDir = path.dirname(fileURLToPath(import.meta.url))
const backendTarget = "http://127.0.0.1:8000"

function officeDevHttps(): ServerOptions["https"] {
  const dir = path.join(os.homedir(), ".office-addin-dev-certs")
  const keyPath = path.join(dir, "localhost.key")
  const certPath = path.join(dir, "localhost.crt")
  if (fs.existsSync(keyPath) && fs.existsSync(certPath)) {
    return {
      key: fs.readFileSync(keyPath),
      cert: fs.readFileSync(certPath),
    }
  }
  return undefined
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(rootDir, "./src"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 3000,
    strictPort: true,
    https: officeDevHttps(),
    proxy: {
      "/expertgranskning": { target: backendTarget, changeOrigin: true },
      "/populations": { target: backendTarget, changeOrigin: true },
      "/me": { target: backendTarget, changeOrigin: true },
      "/ws": { target: backendTarget, ws: true, changeOrigin: true },
    },
  },
})
