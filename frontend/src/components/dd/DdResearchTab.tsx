import { useState } from "react"
import type { Job, JobStatus } from "@/api/jobs"
import type { DdResearchDossier } from "@/api/dd"
import { DdResearchGroupPanel } from "@/components/dd/DdResearchGroupPanel"
import { DdResearchPeoplePanel } from "@/components/dd/DdResearchPeoplePanel"
import { findModerbolag } from "@/components/dd/researchGroup"
import { personInvestigated } from "@/components/dd/researchPeople"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { cn } from "@/lib/utils"

export type ResearchSubTab = "group" | "people"

function researchStatusClass(status: JobStatus): string {
  if (status === "succeeded") return "job-status succeeded"
  if (status === "failed") return "job-status failed"
  if (status === "running" || status === "pending") return "job-status running"
  return "job-status"
}

export function DdResearchTab({
  dossier,
  subTab,
  onSubTab,
  selected,
  disabled,
  clearing,
  isGroupJob,
  isContinueJob,
  researchJob,
  companyName,
  companyOrgnr,
  runCreatedAt,
  onMapGroup,
  onMapMore,
  onClear,
  onToggle,
  onInvestigate,
  onInvestigateAll,
  t,
}: {
  dossier: DdResearchDossier | null
  subTab: ResearchSubTab
  onSubTab: (tab: ResearchSubTab) => void
  selected: Set<string>
  disabled: boolean
  clearing: boolean
  isGroupJob: boolean
  isContinueJob: boolean
  researchJob: Job | undefined
  companyName: string
  companyOrgnr: string
  runCreatedAt?: string
  onMapGroup: () => void
  onMapMore: () => void
  onClear: () => void
  onToggle: (name: string, checked: boolean) => void
  onInvestigate: () => void
  onInvestigateAll: () => void
  t: (key: MessageKey, params?: TranslateParams) => string
}) {
  const { intl } = useLocale()
  const [confirmClear, setConfirmClear] = useState(false)
  const pending = dossier?.pending ?? []
  const companies = dossier?.companies ?? []
  const people = dossier?.people ?? []
  const leftover = dossier?.leftover ?? []
  const mapped = companies.length > 0
  const moder = findModerbolag(companies)
  const startedLabel = runCreatedAt
    ? new Intl.DateTimeFormat(intl, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(runCreatedAt))
    : t("common.emDash")

  const selectedPeople = people.filter((person) => selected.has(person.namn))
  const selectedAllInvestigated =
    selectedPeople.length > 0 && selectedPeople.every((person) => personInvestigated(person))
  const allPeopleInvestigated =
    people.length > 0 && people.every((person) => personInvestigated(person))
  const busy = disabled || clearing

  const clearControls = mapped ? (
    confirmClear ? (
      <>
        <button
          type="button"
          className="btn-save"
          disabled={busy}
          onClick={() => setConfirmClear(false)}
        >
          {t("common.cancel")}
        </button>
        <button
          type="button"
          className="btn-run"
          disabled={busy}
          onClick={() => {
            setConfirmClear(false)
            onClear()
          }}
        >
          {clearing ? t("dd.panel.researchClearing") : t("dd.panel.researchClearConfirm")}
        </button>
      </>
    ) : (
      <button
        type="button"
        className="btn-save"
        disabled={busy}
        onClick={() => setConfirmClear(true)}
      >
        {t("dd.panel.researchClear")}
      </button>
    )
  ) : null

  return (
    <div
      id="dd-run-panel-research"
      role="tabpanel"
      aria-labelledby="dd-run-tab-research"
      className="flex min-h-0 flex-1 flex-col"
    >
      <div className="shrink-0">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="flex flex-wrap items-center gap-2 text-lg font-medium text-[color:var(--text-body)]">
              <span>{companyName}</span>
              <span className="rounded-sm border border-[color:var(--db-gold-500)] bg-[color:var(--db-gold-500)]/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[color:var(--db-gold-700)]">
                {t("dd.panel.researchRelation.kandidat")}
              </span>
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {mapped
                ? t("dd.panel.researchGroupMetaMapped", {
                    date: startedLabel,
                    parent: moder?.namn ?? t("common.emDash"),
                  })
                : t("dd.panel.researchCompanyMeta", {
                    date: startedLabel,
                    count: companies.length,
                  })}
              {companyOrgnr ? (
                <span className="ml-2 text-muted-foreground">· {companyOrgnr}</span>
              ) : null}
            </p>
            {confirmClear ? (
              <p className="mt-2 text-sm text-muted-foreground">{t("dd.panel.researchClearHint")}</p>
            ) : null}
          </div>
          {subTab === "group" ? (
            <div className="run-action-bar shrink-0">
              <div className="start-buttons">
                {mapped ? (
                  clearControls
                ) : (
                  <button
                    type="button"
                    className="btn-run"
                    disabled={busy}
                    onClick={onMapGroup}
                  >
                    {isGroupJob && !isContinueJob
                      ? t("dd.panel.researchRunning")
                      : t("dd.panel.researchRun")}
                  </button>
                )}
                {pending.length > 0 ? (
                  <button
                    type="button"
                    className="btn-save"
                    disabled={busy || confirmClear}
                    onClick={onMapMore}
                  >
                    {isContinueJob
                      ? t("dd.panel.researchRunningMore")
                      : t("dd.panel.researchRunMore", { count: pending.length })}
                  </button>
                ) : null}
              </div>
              {researchJob ? (
                <span className={researchStatusClass(researchJob.status)}>
                  {t(`dd.panel.researchStatus.${researchJob.status}`)}
                </span>
              ) : null}
            </div>
          ) : (
            <div className="run-action-bar shrink-0">
              <div className="start-buttons">
                {clearControls}
                <button
                  type="button"
                  className="btn-run"
                  disabled={busy || selected.size === 0 || selectedAllInvestigated || confirmClear}
                  onClick={onInvestigate}
                >
                  {disabled
                    ? t("dd.panel.researchPeopleRunning")
                    : t("dd.panel.researchPeopleRunCount", { count: selected.size })}
                </button>
                <button
                  type="button"
                  className="btn-save"
                  disabled={busy || people.length === 0 || allPeopleInvestigated || confirmClear}
                  onClick={onInvestigateAll}
                >
                  {t("dd.panel.researchPeopleRunAll")}
                </button>
              </div>
              {researchJob ? (
                <span className={researchStatusClass(researchJob.status)}>
                  {t(`dd.panel.researchStatus.${researchJob.status}`)}
                </span>
              ) : null}
            </div>
          )}
        </div>
        {researchJob?.status === "failed" && researchJob.error ? (
          <p className="mb-4 text-sm text-muted-foreground" role="alert">
            {researchJob.error}
          </p>
        ) : null}
        <div
          role="tablist"
          aria-label={t("dd.panel.researchTablistAria")}
          className="mb-6 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
        >
          {(
            [
              {
                id: "group" as const,
                label:
                  companies.length > 0
                    ? t("dd.panel.researchTabGroupCount", { count: companies.length })
                    : t("dd.panel.researchTabGroup"),
              },
              {
                id: "people" as const,
                label:
                  people.length > 0
                    ? t("dd.panel.researchTabPeopleCount", { count: people.length })
                    : t("dd.panel.researchTabPeople"),
              },
            ] as const
          ).map((tab) => {
            const selectedTab = tab.id === subTab
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                id={`dd-research-tab-${tab.id}`}
                aria-selected={selectedTab}
                aria-controls={`dd-research-panel-${tab.id}`}
                tabIndex={selectedTab ? 0 : -1}
                className={cn(
                  "-mb-px border-b-2 px-3 py-2 text-sm",
                  selectedTab
                    ? "border-db-ink-950 font-medium text-[color:var(--text-body)]"
                    : "border-transparent text-muted-foreground hover:text-[color:var(--text-body)]",
                )}
                onClick={() => onSubTab(tab.id)}
              >
                {tab.label}
              </button>
            )
          })}
        </div>
      </div>
      {subTab === "group" ? (
        <div
          id="dd-research-panel-group"
          role="tabpanel"
          aria-labelledby="dd-research-tab-group"
          className="flex min-h-0 flex-1 flex-col overflow-auto"
        >
          <DdResearchGroupPanel
            companies={companies}
            people={people}
            leftover={leftover}
            pending={pending}
            t={t}
          />
        </div>
      ) : (
        <div
          id="dd-research-panel-people"
          role="tabpanel"
          aria-labelledby="dd-research-tab-people"
          className="flex min-h-0 flex-1 flex-col overflow-auto"
        >
          <DdResearchPeoplePanel
            people={people}
            companies={companies}
            leftover={leftover}
            selected={selected}
            disabled={busy}
            onToggle={onToggle}
            t={t}
          />
        </div>
      )}
    </div>
  )
}
