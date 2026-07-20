import type { ReactNode } from "react";

type Role = "admin" | "technician" | "viewer";

type RoleGateProps = {
  role: Role;
  allowed: Role[];
  fallback?: ReactNode;
  children: ReactNode;
};

export function RoleGate({ role, allowed, fallback, children }: RoleGateProps) {
  return allowed.includes(role) ? <>{children}</> : <>{fallback ?? null}</>;
}
