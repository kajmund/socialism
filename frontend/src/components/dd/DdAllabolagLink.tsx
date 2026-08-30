import { allabolagSearchUrl } from "@/components/dd/researchPeople"
import { useLocale } from "@/i18n"

export function DdAllabolagLink({
  namn,
  orgnr = "",
}: {
  namn: string
  orgnr?: string
}) {
  const { t } = useLocale()
  return (
    <a
      href={allabolagSearchUrl(orgnr, namn)}
      target="_blank"
      rel="noreferrer"
      aria-label={t("dd.panel.researchAllabolagLinkAria", { name: namn })}
    >
      {namn}
    </a>
  )
}
