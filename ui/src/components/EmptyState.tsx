import { Link, useInRouterContext } from "react-router-dom";
import type { ReactNode } from "react";

type EmptyStateProps = {
  title: string;
  why: ReactNode;
  action?: { label: string; to: string };
  icon?: ReactNode;
};

export function EmptyState({ title, why, action, icon }: EmptyStateProps) {
  const inRouter = useInRouterContext();
  return (
    <section className="panel empty-state" aria-live="polite">
      {icon ? <span className="empty-state-icon" aria-hidden="true">{icon}</span> : null}
      <h3>{title}</h3>
      <p>{why}</p>
      {action ? inRouter ? <Link className="secondary-button" to={action.to}>{action.label}</Link> : <a className="secondary-button" href={action.to}>{action.label}</a> : null}
    </section>
  );
}
