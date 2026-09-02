import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight, CheckCircle2 } from "lucide-react";

export type WizardStep = {
  id: string;
  title: string;
  description?: string;
};

type WizardProps = {
  steps: WizardStep[];
  activeStep: number;
  isBusy: boolean;
  canContinue: boolean;
  canSubmit: boolean;
  onBack: () => void;
  onNext: () => Promise<void> | void;
  onSubmit: () => Promise<void> | void;
  onClose: () => void;
  children: ReactNode;
  progressLabel?: string;
  title?: string;
  nextLabel?: string;
  submitLabel?: string;
  onStepSelect?: (index: number) => void;
};

export function Wizard({
  steps,
  activeStep,
  isBusy,
  canContinue,
  canSubmit,
  onBack,
  onNext,
  onSubmit,
  onClose,
  children,
  progressLabel,
  title = "Set up your MSP operations",
  nextLabel = "Next",
  submitLabel = "Complete",
  onStepSelect
}: WizardProps) {
  const isLast = activeStep === steps.length - 1;
  const label = isLast ? submitLabel : nextLabel;

  async function handlePrimary() {
    if (isLast) {
      await onSubmit();
      return;
    }
    await onNext();
  }

  return (
    <section className="wizard-panel panel">
      <div className="panel-heading wizard-heading">
        <h2>{title}</h2>
        <button className="icon-button" type="button" onClick={onClose}>Dismiss</button>
      </div>

      <div className="wizard-steps" role="list" aria-label="Onboarding progress">
        {steps.map((step, index) => {
          const isActive = index === activeStep;
          const isDone = index < activeStep;
          const content = <><span>{isDone ? <CheckCircle2 size={16} aria-hidden="true" /> : index + 1}</span><div><strong>{step.title}</strong>{step.description ? <p>{step.description}</p> : null}</div></>;
          return onStepSelect ? (
            <button
              className={`wizard-step ${isActive ? "active" : ""} ${isDone ? "done" : ""}`}
              type="button"
              aria-label={step.title}
              disabled={index > activeStep || isBusy}
              onClick={() => onStepSelect(index)}
              key={step.id}
            >
              {content}
            </button>
          ) : (
            <li
              className={`wizard-step ${isActive ? "active" : ""} ${isDone ? "done" : ""}`}
              aria-current={isActive ? "step" : undefined}
              key={step.id}
            >
              {content}
            </li>
          );
        })}
      </div>

      <div className="wizard-content">
        {children}
      </div>

      <div className="row-actions">
        <button
          type="button"
          className="icon-button"
          disabled={activeStep === 0 || isBusy}
          onClick={onBack}
        >
          <ChevronLeft size={16} aria-hidden="true" />
          Back
        </button>
        <button
          type="button"
          disabled={isBusy || (isLast ? !canSubmit : !canContinue)}
          onClick={() => void handlePrimary()}
        >
          {isBusy ? "Applying..." : label}
          {!isLast ? <ChevronRight size={16} aria-hidden="true" /> : null}
        </button>
      </div>
      {progressLabel ? <p className="screen-note">{progressLabel}</p> : null}
    </section>
  );
}
