"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useEffectEvent,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError, createApi, type Api, type MeOut } from "@/lib/api";
import { useAuthClient } from "@/lib/auth/context";
import { apiUrl } from "@/lib/env";

/** API client bound to the current identity; a 401 signs the user out. */
export function useApi(): Api {
  const auth = useAuthClient();
  return useMemo(
    () =>
      createApi({
        baseUrl: apiUrl,
        getToken: auth.getToken,
        onUnauthorized: () => void auth.signOut(),
      }),
    [auth],
  );
}

export type Query<T> = {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  reload: () => void;
};

/**
 * Minimal fetch-on-change hook. `key` identifies the request: when it
 * changes (or reload() is called) the fetcher runs again; null skips it.
 */
export function useQuery<T>(key: string | null, fetcher: () => Promise<T>): Query<T> {
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<{
    key: string | null;
    version: number;
    data?: T;
    error?: ApiError;
  }>({ key: null, version: -1 });

  const run = useEffectEvent(() => fetcher());

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    run().then(
      (data) => !cancelled && setResult({ key, version, data }),
      (e: unknown) =>
        !cancelled &&
        setResult({
          key,
          version,
          error: e instanceof ApiError ? e : new ApiError(0, "error", String(e)),
        }),
    );
    return () => {
      cancelled = true;
    };
  }, [key, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  const current = result.key === key;
  return {
    // Keep showing the previous data for the same key while reloading.
    data: current ? result.data : undefined,
    error: current && result.version === version ? result.error : undefined,
    loading: key !== null && (!current || result.version !== version),
    reload,
  };
}

const MeContext = createContext<Query<MeOut> | null>(null);

/** Loads /v1/me once signed in (first call also creates our user row). */
export function MeProvider({ children }: { children: ReactNode }) {
  const auth = useAuthClient();
  const api = useApi();
  const key =
    auth.state.status === "signed-in" ? `me:${auth.provider}:${auth.state.email ?? ""}` : null;
  const me = useQuery(key, api.me);
  return <MeContext.Provider value={me}>{children}</MeContext.Provider>;
}

export function useMe(): Query<MeOut> {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe must be used inside <MeProvider>");
  return me;
}
