import { FolderOpen, RefreshCw } from "lucide-react";
import { useState } from "react";

type FolderPickerProps = {
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  disabled?: boolean;
};

type TauriDialog = {
  open: (options: { directory: boolean }) => Promise<string | string[] | null | undefined>;
};

type TauriWindow = Window & {
  __TAURI__?: {
    dialog?: TauriDialog;
  };
};

function toSinglePath(value: string | string[] | null | undefined): string {
  if (Array.isArray(value)) {
    return value[0] ?? "";
  }
  return value ?? "";
}

export function FolderPicker({ label, value, onChange, placeholder, disabled }: FolderPickerProps) {
  const [isSelecting, setIsSelecting] = useState(false);
  const isTauri = typeof window !== "undefined" && typeof (window as TauriWindow).__TAURI__?.dialog?.open === "function";

  async function pickFolder() {
    if (disabled || isSelecting || !isTauri) {
      return;
    }
    setIsSelecting(true);
    try {
      const path = toSinglePath(await (window as TauriWindow).__TAURI__?.dialog?.open({ directory: true }));
      if (path) {
        onChange(path);
      }
    } finally {
      setIsSelecting(false);
    }
  }

  return (
    <label className="folder-picker">
      <span>{label}</span>
      <div className="folder-picker-row">
        <input
          placeholder={placeholder}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
        />
        <button
          className="icon-button"
          type="button"
          disabled={disabled || !isTauri || isSelecting}
          onClick={() => void pickFolder()}
        >
          {isSelecting ? <RefreshCw size={16} aria-hidden="true" /> : <FolderOpen size={16} aria-hidden="true" />}
          Browse
        </button>
      </div>
      {!isTauri ? <p className="screen-note">Running in browser mode; use the text field for folder path.</p> : null}
    </label>
  );
}
