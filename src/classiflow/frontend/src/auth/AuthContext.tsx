import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { fetchCurrentUser, type CurrentUser } from "../api/auth";
import { openOAuthPopup } from "./oauthPopup";
import { getToken, setToken, clearToken } from "./tokenStorage";

interface AuthContextValue {
  user: CurrentUser | null;
  isAdmin: boolean;
  isLoading: boolean;
  login: () => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setIsLoading(false);
      return;
    }
    fetchCurrentUser()
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setIsLoading(false));
  }, []);

  async function login(): Promise<void> {
    const token = await openOAuthPopup();
    setToken(token);
    const currentUser = await fetchCurrentUser();
    setUser(currentUser);
  }

  function logout(): void {
    clearToken();
    setUser(null);
  }

  return (
    <AuthContext.Provider
      value={{ user, isAdmin: user?.isAdmin ?? false, isLoading, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
