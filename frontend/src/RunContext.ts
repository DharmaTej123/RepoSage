import { createContext, useContext } from "react";

export interface RunCtx {
  jobId: string;
  setJobId: (id: string) => void;
}

export const RunContext = createContext<RunCtx>({ jobId: "", setJobId: () => {} });
export const useRun = () => useContext(RunContext);