import { Navigate, Route, Routes } from "react-router-dom"
import { ConfigureRunPage } from "@/pages/ConfigureRunPage"
import { ConfigurationPage } from "@/pages/ConfigurationPage"
import { MessagesPage } from "@/pages/MessagesPage"
import { MessagesWorkshopPage } from "@/pages/MessagesWorkshopPage"
import { PersonaComposerPage } from "@/pages/PersonaComposerPage"
import { PersonasPage } from "@/pages/PersonasPage"
import { PopulationBuilderPage } from "@/pages/PopulationBuilderPage"
import { PopulationDetailPage } from "@/pages/PopulationDetailPage"
import { PopulationsPage } from "@/pages/PopulationsPage"
import { RunsPage } from "@/pages/RunsPage"
import { SimulatorPage } from "@/pages/SimulatorPage"

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

      <Route path="/config" element={<ConfigurationPage />} />

      <Route path="/simulator" element={<SimulatorPage />} />
      <Route path="*" element={<Navigate to="/runs" replace />} />
    </Routes>
  )
}
