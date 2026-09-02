import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Wizard } from "./Wizard";

const steps = [
  { id: "one", title: "One" },
  { id: "two", title: "Two" },
  { id: "three", title: "Three" }
];

function renderWizard(onStepSelect?: (index: number) => void) {
  return render(
    <Wizard
      steps={steps}
      activeStep={1}
      isBusy={false}
      canContinue
      canSubmit
      onBack={vi.fn()}
      onNext={vi.fn()}
      onSubmit={vi.fn()}
      onClose={vi.fn()}
      onStepSelect={onStepSelect}
    >
      Content
    </Wizard>
  );
}

describe("Wizard step controls", () => {
  it("renders progress chips as non-interactive list items without a handler", () => {
    renderWizard();

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("One");
    expect(items[1]).toHaveAttribute("aria-current", "step");
    expect(items[1]).toHaveTextContent("Two");
    expect(screen.queryByRole("button", { name: "One" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Two" })).not.toBeInTheDocument();
  });

  it("only lets a supplied handler select the current or completed steps", () => {
    const onStepSelect = vi.fn();
    renderWizard(onStepSelect);

    fireEvent.click(screen.getByRole("button", { name: "One" }));
    fireEvent.click(screen.getByRole("button", { name: "Two" }));
    expect(onStepSelect.mock.calls.map(([index]) => index)).toEqual([0, 1]);
    expect(screen.getByRole("button", { name: "Three" })).toBeDisabled();
  });
});
