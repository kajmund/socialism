import { Navigate, Outlet } from "react-router-dom"
import { useAuth } from "@/auth/AuthProvider"
import { AuthSplash } from "@/auth/RequireAuth"
import { homePathForUser } from "@/lib/auth"

/** Users without the rattsunderlag module belong elsewhere. */
export function RequireRattsunderlag() {
  const { hasModule, isAdmin, loading, resolvedModules } = useAuth()
  if (loading) return <AuthSplash />
  if (!isAdmin && !hasModule("rattsunderlag")) {
    return <Navigate to={homePathForUser(resolvedModules)} replace />
  }
  return <Outlet />
}
