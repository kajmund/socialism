import { useEffect, useState, type ComponentType, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { getProfile, updateProfile, type Profile } from "@/api/profiles"
import { useAuth } from "@/auth/AuthProvider"
import { AdminShell } from "@/components/layout/AdminShell"
import { ProfileForm } from "@/components/profiles/ProfileForm"
import { AvatarEditor } from "@/components/profiles/AvatarEditor"
import { ProfileProposals } from "@/components/profiles/ProfileProposals"
import { useLocale } from "@/i18n"

type ProfilePageProps = {
  Shell?: ComponentType<{ children: ReactNode }>
  embedded?: boolean
}

export function ProfilePage({
  Shell = AdminShell,
  embedded = false,
}: ProfilePageProps = {}) {
  const { t } = useLocale()
  const { refreshProfile } = useAuth()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(false)
  async function reload() {
    setProfile(await getProfile())
    await refreshProfile()
  }
  useEffect(() => {
    void getProfile().then(setProfile).catch(() => setError(true))
  }, [])

  return (
    <Shell>
      <div className={"wrap admin-page" + (embedded ? " admin-page-embedded" : "")}>
        {!embedded ? (
          <div className="admin-page-chrome pb-6">
            <Link to="/">{t("profile.back")}</Link>
            <h1 className="mt-3 text-2xl font-semibold">{t("profile.title")}</h1>
          </div>
        ) : null}
        <div className="admin-page-body grid content-start gap-6">
          {saved ? <p role="status">{t("profile.saved")}</p> : null}
          {error ? <p role="alert">{t("profile.loadError")}</p> : null}
          {profile ? (
            <>
              <ProfileForm
                key={profile.profile_revision}
                values={profile}
                onSave={async (changes) => {
                  setSaved(false)
                  await updateProfile(changes)
                  await reload()
                  setSaved(true)
                }}
              />
              <AvatarEditor
                userId={profile.id}
                path={profile.avatar_url}
                onSaved={reload}
              />
            </>
          ) : null}
          <ProfileProposals onSaved={reload} />
        </div>
      </div>
    </Shell>
  )
}
