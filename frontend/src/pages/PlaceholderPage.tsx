import { AdminShell } from "@/components/layout/AdminShell"
import { Link } from "react-router-dom"

type PlaceholderPageProps = {
  title: string
  description: string
}

export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <AdminShell>
      <main className="mx-auto max-w-[1240px] px-10 py-16">
        <h1 className="text-4xl font-light tracking-tight">{title}</h1>
        <p className="mt-3 max-w-xl text-sm text-db-ink-900/70">{description}</p>
        <Link
          to="/runs/new"
          className="admin-cta mt-8 inline-flex h-9 items-center rounded-full bg-db-black px-5 text-sm text-db-ink-0 no-underline hover:bg-db-ink-800"
        >
          Skapa ny körning
        </Link>
      </main>
    </AdminShell>
  )
}
