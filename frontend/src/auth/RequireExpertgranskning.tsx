import { Navigate, Outlet } from "react-router-dom"
import { useAuth } from "@/auth/AuthProvider"
import { AuthSplash } from "@/auth/RequireAuth"
import { homePathForUser } from "@/lib/auth"

/** Users without the expertgranskning module belong elsewhere. */
export function RequireExpertgranskning() {
  const { hasModule, loading, resolvedModules } = useAuth()
  if (loading) return <AuthSplash />
  if (!hasModule("expertgranskning")) {
    return <Navigate to={homePathForUser(resolvedModules)} replace />
  }
  return <Outlet />
}
