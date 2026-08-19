import { Navigate, Outlet } from "react-router-dom"
import { useAuth } from "@/auth/AuthProvider"
import { AuthSplash } from "@/auth/RequireAuth"

export function RequireAdmin() {
  const { loading, isAdmin } = useAuth()

  if (loading) return <AuthSplash />
  if (!isAdmin) return <Navigate to="/" replace />
  return <Outlet />
}
