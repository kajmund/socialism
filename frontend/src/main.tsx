import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import App from "@/App"
import { env } from "@/lib/env"
import "@/index.css"
import "@/styles/simulator.css"
import "@/styles/admin-runs.css"

// Touch env at boot so missing config fails fast.
void env

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
