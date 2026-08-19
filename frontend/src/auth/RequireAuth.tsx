import { Navigate, Outlet, useLocation } from "react-router-dom"
import { useAuth } from "@/auth/AuthProvider"

export function AuthSplash() {
  return <div className="min-h-svh bg-db-black" aria-hidden="true" />
}

export function RequireAuth() {
  const { session, loading } = useAuth()
  const location = useLocation()

  if (loading) return <AuthSplash />
  if (!session) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}
