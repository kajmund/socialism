import { Navigate, Outlet } from "react-router-dom"
import { useAuth } from "@/auth/AuthProvider"
import { homePathForRole } from "@/lib/auth"

/** Redirect non-bolag users away from bolag-only routes. */
export function RequireBolag() {
  const { role, loading } = useAuth()
  if (loading) return <div className="min-h-svh bg-db-black" aria-hidden="true" />
  if (role !== "bolag") return <Navigate to={homePathForRole(role)} replace />
  return <Outlet />
}
