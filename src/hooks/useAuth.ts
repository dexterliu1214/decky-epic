import { useCallback, useEffect, useState } from "react";
import { authFinish, authLogout, authStatus } from "../api";
import type { AuthStatus } from "../types";

export function useAuth() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await authStatus());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const finish = useCallback(
    async (code: string) => {
      const res = await authFinish(code);
      await refresh();
      return res;
    },
    [refresh],
  );

  const logout = useCallback(async () => {
    await authLogout();
    await refresh();
  }, [refresh]);

  return { status, loading, refresh, finish, logout };
}
