// SPDX-License-Identifier: AGPL-3.0-only
// Additional terms: ../../../../ADDITIONAL_TERMS.md

export function WaitAttribution() {
  return (
    <footer
      aria-label="WAIT attribution"
      style={{
        alignItems: "center",
        color: "#60706a",
        display: "flex",
        fontSize: "0.8rem",
        gap: "0.35rem",
        justifyContent: "center",
        marginTop: "2rem",
        padding: "1rem 0"
      }}
    >
      <span>Powered by <strong style={{ color: "inherit" }}>WAIT</strong></span>
    </footer>
  );
}
