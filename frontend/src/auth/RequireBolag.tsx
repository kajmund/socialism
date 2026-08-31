import { Navigate, Outlet } from "react-router-dom"
import { useAuth } from "@/auth/AuthProvider"
import { AuthSplash } from "@/auth/RequireAuth"
import { homePathForUser } from "@/lib/auth"

/** Redirect users without the DD module away from bolag routes. */
export function RequireBolag() {
  const { hasModule, loading, resolvedModules } = useAuth()
  if (loading) return <AuthSplash />
  if (!hasModule("dd")) return <Navigate to={homePathForUser(resolvedModules)} replace />
  return <Outlet />
}
