import { Navigate, Outlet } from "react-router-dom"
import { useAuth } from "@/auth/AuthProvider"
import { AuthSplash } from "@/auth/RequireAuth"
import { homePathForUser } from "@/lib/auth"

export function RequireTabularReview() {
  const { hasModule, loading, resolvedModules } = useAuth()
  if (loading) return <AuthSplash />
  if (!hasModule("tabular_review")) {
    return <Navigate to={homePathForUser(resolvedModules)} replace />
  }
  return <Outlet />
}
