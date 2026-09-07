import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import { App } from "@/App"
import { LocaleProvider } from "@/i18n/LocaleContext"
import { officeReady } from "@/lib/office"

import "./index.css"

void officeReady().then(() => {
  const root = document.getElementById("root")
  if (!root) {
    throw new Error("Missing #root")
  }
  document.documentElement.lang = "sv"
  createRoot(root).render(
    <StrictMode>
      <LocaleProvider>
        <App />
      </LocaleProvider>
    </StrictMode>,
  )
})
