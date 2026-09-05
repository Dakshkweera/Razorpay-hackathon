import { useState, type FormEvent } from "react";
import { ThemeToggle } from "./ThemeToggle";

export interface AuthedUser {
  name: string;
  email: string;
}

export function Auth({
  mode: initialMode,
  onAuthenticated,
  onBack,
}: {
  mode: "signin" | "register";
  onAuthenticated: (user: AuthedUser) => void;
  onBack: () => void;
}) {
  const [mode, setMode] = useState(initialMode);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const displayName = name.trim() || email.split("@")[0] || "Operator";
    onAuthenticated({
      name: displayName,
      email: email.trim() || "operator@merchant.example",
    });
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-5 screen-enter">
      <div className="w-full max-w-[380px]">
        <div className="mb-6 flex items-center justify-between">
          <button onClick={onBack} className="text-[12px] text-ink-faint hover:text-ink-soft">
            ← Settlement Explainer
          </button>
          <ThemeToggle />
        </div>

        <div className="rounded-lg border border-line bg-surface p-6">
          <div className="mb-5 flex gap-1 rounded bg-ground p-1">
            <button
              type="button"
              onClick={() => setMode("signin")}
              className={`flex-1 rounded px-3 py-1.5 text-[12px] font-medium ${
                mode === "signin" ? "bg-surface text-ink shadow-sm" : "text-ink-faint"
              }`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => setMode("register")}
              className={`flex-1 rounded px-3 py-1.5 text-[12px] font-medium ${
                mode === "register" ? "bg-surface text-ink shadow-sm" : "text-ink-faint"
              }`}
            >
              Create account
            </button>
          </div>

          <h2 className="text-[15px] font-semibold tracking-tight">
            {mode === "signin" ? "Welcome back" : "Create your account"}
          </h2>
          <p className="mt-1 text-[12px] text-ink-faint">
            {mode === "signin"
              ? "Sign in to your merchant workspace."
              : "Set up access for your finance team."}
          </p>

          <form onSubmit={submit} className="mt-5 grid gap-3">
            {mode === "register" && (
              <Field label="Full name" value={name} onChange={setName} placeholder="Asha Rao" />
            )}
            <Field
              label="Work email"
              value={email}
              onChange={setEmail}
              placeholder="asha@merchant.com"
              type="email"
            />
            <Field
              label="Password"
              value={password}
              onChange={setPassword}
              placeholder="••••••••"
              type="password"
            />

            <button
              type="submit"
              className="mt-2 rounded bg-ink px-3 py-2 text-[13px] font-medium text-ground"
            >
              {mode === "signin" ? "Sign in" : "Create account"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="grid gap-1">
      <span className="text-[11px] font-medium text-ink-soft">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="rounded border border-line-strong bg-ground px-2.5 py-1.5 text-[13px] text-ink outline-none focus:border-info"
      />
    </label>
  );
}
