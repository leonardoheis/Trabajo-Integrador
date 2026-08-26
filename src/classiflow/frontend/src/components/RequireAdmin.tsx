import { Navigate, Outlet } from "react-router";
import { useAuth } from "../auth/AuthContext";

export default function RequireAdmin() {
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }
  return <Outlet />;
}
