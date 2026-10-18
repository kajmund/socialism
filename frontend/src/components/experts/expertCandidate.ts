import { editableToWrite, type ExpertCandidate } from "@/api/personas"
import { blankEditableExpert, personaInitials } from "@/data/library"

export function expertWriteFromCandidate(candidate: ExpertCandidate, customerId: number) {
  const profile = blankEditableExpert()
  profile.name = candidate.name
  profile.initials = personaInitials(candidate.name)
  profile.beskrivning = candidate.description || "—"
  profile.kompetensomrade = candidate.kompetensomrade || "—"
  profile.radgivningsstil = candidate.radgivningsstil || "—"
  profile.yrkesbakgrund = candidate.yrkesbakgrund || "—"
  profile.professionell_anekdot = candidate.professionell_anekdot || "—"
  profile.yrke = candidate.yrkesbakgrund || "—"
  return editableToWrite(profile, "beskrivning", candidate.description, {
    kind: "expert",
    customerId,
  })
}
