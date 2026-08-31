import { Navigate, Outlet } from "react-router-dom"
import { AuthSplash } from "@/auth/RequireAuth"
import { useAuth } from "@/auth/AuthProvider"
import { homePathForUser } from "@/lib/auth"

/** Opinionssimulator routes — users without the politik module belong elsewhere. */
export function RequireOsUser() {
  const { hasModule, loading, resolvedModules } = useAuth()
  if (loading) return <AuthSplash />
  if (!hasModule("politik")) return <Navigate to={homePathForUser(resolvedModules)} replace />
  return <Outlet />
}
