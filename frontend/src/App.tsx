import { Navigate, Route, Routes } from "react-router-dom"
import { ConfigureRunPage } from "@/pages/ConfigureRunPage"
import { ConfigurationPage } from "@/pages/ConfigurationPage"
import { JobsPage } from "@/pages/JobsPage"
import { MessagesPage } from "@/pages/MessagesPage"
import { MessagesWorkshopPage } from "@/pages/MessagesWorkshopPage"
import { PersonaComposerPage } from "@/pages/PersonaComposerPage"
import { PersonasPage } from "@/pages/PersonasPage"
import { PopulationBuilderPage } from "@/pages/PopulationBuilderPage"
import { PopulationDetailPage } from "@/pages/PopulationDetailPage"
import { PopulationsPage } from "@/pages/PopulationsPage"
import { ReportPage } from "@/pages/ReportPage"
import { RunsPage } from "@/pages/RunsPage"

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/runs" replace />} />
      <Route path="/runs" element={<RunsPage />} />
      <Route path="/runs/new" element={<ConfigureRunPage />} />
      <Route path="/runs/:id/edit" element={<ConfigureRunPage />} />

      <Route path="/personas" element={<PersonasPage />} />
      <Route path="/personas/new" element={<PersonaComposerPage />} />
      <Route path="/personas/:id" element={<PersonaComposerPage />} />

      <Route path="/populations" element={<PopulationsPage />} />
      <Route path="/populations/new" element={<PopulationBuilderPage />} />
      <Route path="/populations/:id" element={<PopulationDetailPage />} />
      <Route path="/populations/:id/edit" element={<PopulationBuilderPage />} />

      <Route path="/messages" element={<MessagesPage />} />
      <Route path="/messages/new" element={<MessagesWorkshopPage />} />
      <Route path="/messages/:id/edit" element={<MessagesWorkshopPage />} />

      <Route path="/config" element={<ConfigurationPage />} />
      <Route path="/jobs" element={<JobsPage />} />
      <Route path="/reports/:id" element={<ReportPage />} />

      <Route path="*" element={<Navigate to="/runs" replace />} />
    </Routes>
  )
}
