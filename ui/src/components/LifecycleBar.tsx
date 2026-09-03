import { CheckCircle2, Circle } from "lucide-react";
import { SOLUTION_LIFECYCLE_STAGES, solutionLifecycle, type SolutionLifecycleInput } from "../lib/solutionLifecycle";

export function LifecycleBar({ record }: { record: SolutionLifecycleInput | null | undefined }) {
  const lifecycle = solutionLifecycle(record);
  if (lifecycle.stage === "review-only") {
    return <div className="lifecycle-bar review-only" aria-label="Solution lifecycle"><strong>Lifecycle</strong><span className="lifecycle-current">Review-only</span></div>;
  }
  return (
    <div className="lifecycle-bar" aria-label="Solution lifecycle">
      <strong>Lifecycle</strong>
      <ol>
        {SOLUTION_LIFECYCLE_STAGES.map((item, index) => <li key={item.stage} className={index < lifecycle.index ? "complete" : index === lifecycle.index ? "current" : ""}>{index <= lifecycle.index ? <CheckCircle2 size={15} aria-hidden="true" /> : <Circle size={15} aria-hidden="true" />}<span>{item.label}</span></li>)}
      </ol>
      <span className="lifecycle-current">Current: {lifecycle.label}</span>
    </div>
  );
}
