import { BellRing, BookCheck, CalendarClock, MessageSquareText } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ErrorNote } from "../components/ui";
import { useAuth } from "../lib/auth";

const FEATURES = [
  { icon: BellRing, text: "Finds the last day to cancel every auto-renewal and emails your team before it passes" },
  {
    icon: BookCheck,
    text: "Checks each contract against your own rulebook: notice periods, liability caps, approvals",
  },
  { icon: CalendarClock, text: "Puts every deadline in Outlook or Google Calendar, with reminders" },
  { icon: MessageSquareText, text: "Answers questions across all your documents, citing the exact clause" },
];

export function LoginPage() {
  const { user, login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [org, setOrg] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(org, name, email, password);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden bg-night px-14 py-12 text-white lg:flex lg:flex-col">
        <div className="absolute -right-24 -top-24 size-96 rounded-full bg-brand-500/20 blur-3xl" />
        <div className="relative flex items-center gap-2.5">
          <div className="grid size-9 place-items-center rounded-lg bg-brand-500 font-bold">D</div>
          <span className="text-lg font-semibold">DocPilot</span>
        </div>
        <div className="relative mt-auto max-w-lg">
          <div className="kicker !text-brand-200">Contract deadlines & risk, powered by AI</div>
          <h1 className="mt-3 text-4xl font-semibold leading-tight tracking-tight">
            Never miss a contract renewal or notice deadline again.
          </h1>
          <ul className="mt-8 space-y-4">
            {FEATURES.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-start gap-3 text-brand-50/90">
                <Icon className="mt-0.5 size-5 shrink-0 text-brand-200" />
                {text}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative mt-auto pt-10 text-xs text-brand-100/50">
          Portfolio demo · FastAPI · React · Claude · PostgreSQL · Kubernetes
        </p>
      </section>

      <section className="flex items-center justify-center px-6 py-12">
        <form
          onSubmit={submit}
          className="w-full max-w-sm space-y-5"
          aria-label={mode === "login" ? "Sign in" : "Create account"}
        >
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">
              {mode === "login" ? "Welcome back" : "Create your workspace"}
            </h2>
            <p className="mt-1 text-sm text-muted">
              {mode === "login" ? "Sign in to your DocPilot workspace." : "You'll be the admin of a new organization."}
            </p>
          </div>

          {mode === "register" && (
            <>
              <div>
                <label className="label" htmlFor="org">
                  Organization
                </label>
                <input
                  id="org"
                  className="input"
                  value={org}
                  onChange={(e) => setOrg(e.target.value)}
                  required
                  minLength={2}
                />
              </div>
              <div>
                <label className="label" htmlFor="name">
                  Your name
                </label>
                <input id="name" className="input" value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
            </>
          )}
          <div>
            <label className="label" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="label" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>

          <ErrorNote error={error} />

          <button className="btn-primary w-full py-2.5" disabled={busy} type="submit">
            {busy ? "Please wait..." : mode === "login" ? "Sign in" : "Create workspace"}
          </button>

          <p className="text-center text-sm text-muted">
            {mode === "login" ? "New here? " : "Already have an account? "}
            <button
              type="button"
              className="font-medium text-brand-600 hover:underline"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError(null);
              }}
            >
              {mode === "login" ? "Create a workspace" : "Sign in"}
            </button>
          </p>
          {mode === "login" && (
            <p className="rounded-lg border border-line bg-white px-3 py-2 text-xs text-muted">
              Running the seeded demo? Credentials are listed in <code>backend/scripts/seed.py</code>.
            </p>
          )}
        </form>
      </section>
    </div>
  );
}
