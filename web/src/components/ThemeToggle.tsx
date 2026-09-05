import { useState } from "react";
import { applyTheme, type Theme } from "../lib/theme";

export function ThemeToggle({ className = "" }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>(
    () => (document.documentElement.dataset.theme as Theme | undefined) ?? "light",
  );

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
  };

  return (
    <button
      onClick={toggle}
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      className={`rounded border border-line-strong px-2 py-1 text-[11px] font-medium text-ink-soft hover:bg-ground ${className}`}
    >
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
