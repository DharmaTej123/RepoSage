import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RunResults } from "../api/types";

export function useResults(jobId: string) {
  const [data, setData] = useState<RunResults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!jobId) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .results(jobId)
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [jobId]);

  return { data, error, loading };
}