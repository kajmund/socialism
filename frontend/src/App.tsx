import { Navigate, Route, Routes, useParams } from "react-router-dom"
import { HelpChatWidget } from "@/components/help/HelpChatWidget"
import { ToolsShell } from "@/components/layout/ToolsShell"
import { AnchorSetEditorPage } from "@/pages/AnchorSetEditorPage"
import { AnchorSetsPage } from "@/pages/AnchorSetsPage"
import { ConfigureRunPage } from "@/pages/ConfigureRunPage"
import { ConfigurationEditorPage } from "@/pages/ConfigurationEditorPage"
import { ConfigurationsPage } from "@/pages/ConfigurationsPage"
import { DashboardPage } from "@/pages/DashboardPage"
import { EmbeddingCachePage } from "@/pages/EmbeddingCachePage"
import { FeedbackPage } from "@/pages/FeedbackPage"
import { JobsPage } from "@/pages/JobsPage"
import { MessagesPage } from "@/pages/MessagesPage"
import { MessagesWorkshopPage } from "@/pages/MessagesWorkshopPage"
import { PersonaComposerPage } from "@/pages/PersonaComposerPage"
import { PersonasPage } from "@/pages/PersonasPage"
import { PlaygroundPage } from "@/pages/PlaygroundPage"
import { PopulationBuilderPage } from "@/pages/PopulationBuilderPage"
import { PopulationDetailPage } from "@/pages/PopulationDetailPage"
import { PopulationsPage } from "@/pages/PopulationsPage"
import { ReportPage } from "@/pages/ReportPage"
import { ReportsPage } from "@/pages/ReportsPage"
import { RunsPage } from "@/pages/RunsPage"

function RedirectPopulationEdit() {
  const { id } = useParams<{ id: string }>()
  return <Navigate to={`/populations/${id}`} replace />
}

function RedirectConfigurationEdit() {
  const { id } = useParams<{ id: string }>()
  return <Navigate to={`/tools/configurations/${id}/edit`} replace />
}

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/new" element={<ConfigureRunPage />} />
        <Route path="/runs/:id/edit" element={<ConfigureRunPage />} />

        <Route path="/personas" element={<PersonasPage />} />
        <Route path="/personas/new" element={<PersonaComposerPage />} />
        <Route path="/personas/:id" element={<PersonaComposerPage />} />

        <Route path="/populations" element={<PopulationsPage />} />
        <Route path="/populations/new" element={<PopulationBuilderPage />} />
        <Route path="/populations/:id" element={<PopulationDetailPage />} />
        <Route path="/populations/:id/edit" element={<RedirectPopulationEdit />} />

        <Route path="/messages" element={<MessagesPage />} />
        <Route path="/messages/new" element={<MessagesWorkshopPage />} />
        <Route path="/messages/:id/edit" element={<MessagesWorkshopPage />} />

        <Route path="/tools" element={<ToolsShell />}>
          <Route index element={<Navigate to="configurations" replace />} />
          <Route path="configurations" element={<ConfigurationsPage />} />
          <Route path="configurations/new" element={<ConfigurationEditorPage />} />
          <Route path="configurations/:id/edit" element={<ConfigurationEditorPage />} />
          <Route path="anchor-sets" element={<AnchorSetsPage />} />
          <Route path="anchor-sets/new" element={<AnchorSetEditorPage />} />
          <Route path="anchor-sets/:id/edit" element={<AnchorSetEditorPage />} />
          <Route path="playground" element={<PlaygroundPage />} />
          <Route path="cache" element={<EmbeddingCachePage />} />
        </Route>

        <Route path="/configurations" element={<Navigate to="/tools/configurations" replace />} />
        <Route
          path="/configurations/new"
          element={<Navigate to="/tools/configurations/new" replace />}
        />
        <Route path="/configurations/:id/edit" element={<RedirectConfigurationEdit />} />
        <Route path="/config" element={<Navigate to="/tools/configurations" replace />} />
        <Route path="/playground" element={<Navigate to="/tools/playground" replace />} />

        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/feedback" element={<FeedbackPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/reports/:id" element={<ReportPage />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <HelpChatWidget />
    </>
  )
}
