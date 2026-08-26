import { Navigate, Outlet } from "react-router";
import { useAuth } from "../auth/AuthContext";

export default function RequireAuth() {
  const { user, isLoading } = useAuth();
  if (isLoading) {
    return <p>Loading...</p>;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}
