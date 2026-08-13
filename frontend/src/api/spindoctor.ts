import { api } from "@/lib/api"

export type SpindoctorRole = "user" | "assistant"

export type SpindoctorMessage = {
  id: number
  role: SpindoctorRole
  content: string
  created_at: string
}

export function listSpindoctorMessages(reportId: string): Promise<SpindoctorMessage[]> {
  return api.get<SpindoctorMessage[]>("/spindoctor/messages", { report_id: reportId })
}

export function clearSpindoctorMessages(reportId: string): Promise<void> {
  return api.delete<void>("/spindoctor/messages", { report_id: reportId })
}
