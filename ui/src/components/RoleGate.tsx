import type { ReactNode } from "react";

type Role = "admin" | "technician" | "viewer";

type RoleGateProps = {
  role: Role;
  resolved?: boolean;
  allowed: Role[];
  fallback?: ReactNode;
  children: ReactNode;
};

export function RoleGate({ role, resolved = true, allowed, fallback, children }: RoleGateProps) {
  return resolved && allowed.includes(role) ? <>{children}</> : <>{fallback ?? null}</>;
}
