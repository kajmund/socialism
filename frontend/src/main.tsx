import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import App from "@/App"
import { LocaleProvider } from "@/i18n"
import { env } from "@/lib/env"
import { JobsRealtimeProvider } from "@/realtime/JobsRealtimeProvider"
import { ReportsRealtimeProvider } from "@/realtime/ReportsRealtimeProvider"
import "@/index.css"
import "@/styles/admin-runs.css"

// Touch env at boot so missing config fails fast.
void env

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <LocaleProvider>
        <JobsRealtimeProvider>
          <ReportsRealtimeProvider>
            <App />
          </ReportsRealtimeProvider>
        </JobsRealtimeProvider>
      </LocaleProvider>
    </BrowserRouter>
  </StrictMode>,
)
