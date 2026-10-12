import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler, tokenStore } from "./api";
import type { Role, TokenResponse, User } from "./types";

interface AuthState {
  user: User | null;
  orgName: string;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (org: string, name: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  can: (minimum: Role) => boolean;
}

const RANK: Record<Role, number> = { viewer: 0, member: 1, admin: 2 };
const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [orgName, setOrgName] = useState("");
  const [loading, setLoading] = useState(() => Boolean(tokenStore.get()));

  const accept = useCallback((res: TokenResponse) => {
    tokenStore.set(res.access_token);
    setUser(res.user);
    setOrgName(res.org_name);
  }, []);

  const logout = useCallback(() => {
    tokenStore.set(null);
    setUser(null);
    qc.clear();
  }, [qc]);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!tokenStore.get()) return;
    api
      .me()
      .then(accept)
      .catch(() => tokenStore.set(null))
      .finally(() => setLoading(false));
  }, [accept, logout]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      orgName,
      loading,
      login: async (email, password) => accept(await api.login(email, password)),
      register: async (org, name, email, password) => accept(await api.register(org, name, email, password)),
      logout,
      can: (minimum) => (user ? RANK[user.role] >= RANK[minimum] : false),
    }),
    [user, orgName, loading, accept, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
