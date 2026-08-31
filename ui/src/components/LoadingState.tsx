type LoadingStateProps = {
  label?: string;
};

export function LoadingState({ label = "Loading…" }: LoadingStateProps) {
  return (
    <div className="panel loading-state" aria-busy="true" aria-live="polite">
      <span className="loading-state-line" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
