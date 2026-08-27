import { Navigate, Outlet } from "react-router-dom"
import { AuthSplash } from "@/auth/RequireAuth"
import { useAuth } from "@/auth/AuthProvider"

/** Opinionssimulator routes — bolag users belong on /bolag. */
export function RequireOsUser() {
  const { role, loading } = useAuth()
  if (loading) return <AuthSplash />
  if (role === "bolag") return <Navigate to="/bolag" replace />
  return <Outlet />
}
