import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FolderPicker } from "./FolderPicker";

describe("FolderPicker in the Linux browser UI", () => {
  it("labels the path separately from its unavailable native browse control", () => {
    const onChange = vi.fn();
    render(<FolderPicker label="Project folder" value="" onChange={onChange} />);
    const input = screen.getByRole("textbox", { name: "Project folder" });
    expect(input).toHaveAccessibleDescription("Running in browser mode; use the text field for folder path.");
    expect(screen.getByRole("button", { name: "Browse" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "/tmp/disposable-project" } });
    expect(onChange).toHaveBeenCalledWith("/tmp/disposable-project");
  });
});
