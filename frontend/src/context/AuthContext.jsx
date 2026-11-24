import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getMe, login as apiLogin, logout as apiLogout, register as apiRegister } from "../services/api";

/** Who is signed in. The session itself lives in an HttpOnly cookie, so no token is ever visible to page scripts. */
const Ctx = createContext(null);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getMe().then((r) => setUser(r.data)).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);

  // a data request got a 401 (session expired, signed out on another device, password changed)
  useEffect(() => {
    const onExpired = () => setUser(null);
    window.addEventListener("phr:unauthorized", onExpired);
    return () => window.removeEventListener("phr:unauthorized", onExpired);
  }, []);

  const login = useCallback(async (email, password) => setUser((await apiLogin(email, password)).data), []);
  const register = useCallback(async (email, name, password) => setUser((await apiRegister(email, name, password)).data), []);
  const logout = useCallback(async () => {
    try { await apiLogout(); } catch { /* already signed out */ }
    setUser(null);
  }, []);

  const reloadUser = useCallback(() => getMe().then((r) => setUser(r.data)).catch(() => {}), []);
  const value = useMemo(() => ({ user, loading, login, register, logout, reloadUser }),
    [user, loading, login, register, logout, reloadUser]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
