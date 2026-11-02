"use client";

import { createContext, useContext, type ReactNode } from "react";

import { useWorkspace, type WorkspaceController } from "@/hooks/use-workspace";

const WorkspaceContext = createContext<WorkspaceController | null>(null);

/**
 * Owns the single workspace controller so the sticky header (Run demo) and the
 * workspace panels act on the same state.
 */
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const controller = useWorkspace();
  return (
    <WorkspaceContext.Provider value={controller}>{children}</WorkspaceContext.Provider>
  );
}

export function useWorkspaceContext(): WorkspaceController {
  const controller = useContext(WorkspaceContext);
  if (!controller) {
    throw new Error("useWorkspaceContext must be used inside WorkspaceProvider");
  }
  return controller;
}
