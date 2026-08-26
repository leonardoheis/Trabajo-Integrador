import { useNavigate } from "react-router";
import { useAuth } from "../auth/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();

  async function handleLogin(): Promise<void> {
    await login();
    navigate("/");
  }

  return (
    <div className="flex h-screen items-center justify-center bg-[var(--color-bg)]">
      <button
        onClick={handleLogin}
        className="rounded-md bg-[var(--color-accent)] px-6 py-3 text-white"
      >
        Sign in with Google
      </button>
    </div>
  );
}
