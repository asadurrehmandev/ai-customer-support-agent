import { useEffect, useState } from "react";
import { NavLink, Outlet, Route, Routes } from "react-router-dom";
import { llmKey, login, logout, setLlmKey } from "./api.ts";
import { Console } from "./pages/Console.tsx";
import { Inbox } from "./pages/Inbox.tsx";
import { Knowledge } from "./pages/Knowledge.tsx";
import { Metrics } from "./pages/Metrics.tsx";
import { Shop } from "./pages/Shop.tsx";

const NAV = [
  { to: "/", label: "Conversations", end: true },
  { to: "/inbox", label: "Inbox", end: false },
  { to: "/knowledge", label: "Knowledge", end: false },
  { to: "/metrics", label: "Metrics", end: false },
];

export default function App() {
  return (
    <Routes>
      <Route path="/shop" element={<Shop />} />
      <Route element={<Shell />}>
        <Route path="/" element={<Console />} />
        <Route path="/conversations/:id" element={<Console />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/knowledge" element={<Knowledge />} />
        <Route path="/knowledge/:id" element={<Knowledge />} />
        <Route path="/metrics" element={<Metrics />} />
      </Route>
    </Routes>
  );
}

function Shell() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || "light");
  const [key, setKey] = useState(llmKey());
  const [session, setSession] = useState<"checking" | "in" | "out">("checking");

  useEffect(() => {
    let stop = false;
    fetch("/api/auth/session", { credentials: "include" })
      .then((response) => {
        if (!stop) setSession(response.ok ? "in" : "out");
      })
      .catch(() => {
        if (!stop) setSession("out");
      });
    const onUnauthorized = () => setSession("out");
    window.addEventListener("keel-unauthorized", onUnauthorized);
    return () => {
      stop = true;
      window.removeEventListener("keel-unauthorized", onUnauthorized);
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("keel.theme", theme);
  }, [theme]);

  const live = key.length > 0;
  const banner = live
    ? "Live model for this tab. The key stays in session storage and is not saved on the server."
    : "Demo mode: sample responses. Add your API key for live AI.";

  if (session !== "in") {
    return <Login checking={session === "checking"} onSuccess={() => setSession("in")} />;
  }

  return (
    <div className="flex h-dvh flex-col">
      <div className="bg-yellow px-4 py-2 text-sm text-[#141816]">{banner}</div>
      <div className="grid min-h-0 flex-1 grid-cols-1 pb-14 md:grid-cols-[232px_minmax(0,1fr)] md:pb-0">
        <aside className="hidden flex-col border-r border-line bg-pine text-foam md:flex">
          <div className="px-4 pt-5 pb-4">
            <a href="/" className="flex items-center gap-2 text-lg font-bold text-foam no-underline">
              <Mark />
              Keel
            </a>
            <p className="mt-2 text-sm text-foam/80">Marlow & Hale</p>
          </div>
          <nav className="flex flex-col gap-1 px-2" aria-label="Console">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-2 text-sm no-underline ${isActive ? "bg-yellow font-bold text-[#141816]" : "text-foam hover:bg-foam/10"}`
                }
              >
                {item.label}
              </NavLink>
            ))}
            <a href="/shop" className="rounded-lg px-3 py-2 text-sm text-foam no-underline hover:bg-foam/10">
              Shop preview
            </a>
          </nav>
          <div className="mt-auto border-t border-foam/15 p-4">
            <KeyField
              id="llm-key-desk"
              value={key}
              onChange={(value) => {
                setLlmKey(value);
                setKey(llmKey());
              }}
            />
            <button
              type="button"
              className="mt-3 w-full rounded-lg border border-foam/30 px-3 py-2 text-sm text-foam"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? "Light theme" : "Dark theme"}
            </button>
            <button
              type="button"
              className="mt-2 w-full rounded-lg px-3 py-2 text-sm text-foam underline"
              onClick={() => void logout().then(() => setSession("out"))}
            >
              Sign out
            </button>
          </div>
        </aside>
        <div className="flex min-h-0 flex-col">
          <header className="flex items-center justify-between gap-3 border-b border-line bg-sheet px-4 py-3 md:hidden">
            <a href="/" className="flex items-center gap-2 font-bold text-ink no-underline">
              <Mark />
              Keel
            </a>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="rounded-lg border border-line px-3 py-1 text-sm"
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              >
                {theme === "dark" ? "Light" : "Dark"}
              </button>
              <button type="button" className="rounded-lg border border-line px-3 py-1 text-sm" onClick={() => void logout().then(() => setSession("out"))}>
                Sign out
              </button>
            </div>
          </header>
          <div className="border-b border-line bg-sheet px-4 py-3 md:hidden">
            <KeyField
              id="llm-key-mobile"
              value={key}
              onChange={(value) => {
                setLlmKey(value);
                setKey(llmKey());
              }}
            />
          </div>
          <main className="min-h-0 flex-1 overflow-hidden">
            <Outlet />
          </main>
        </div>
      </div>
      <nav className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-4 border-t border-line bg-sheet md:hidden" aria-label="Mobile">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `px-1 py-2 text-center text-xs no-underline ${isActive ? "bg-yellow font-bold text-[#141816]" : "text-ink"}`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

function Login({ checking, onSuccess }: { checking: boolean; onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  return (
    <div className="grid min-h-dvh place-items-center bg-canvas px-4">
      <div className="w-full max-w-md rounded-2xl border border-line bg-sheet p-6">
        <div className="flex items-center gap-2 text-ink">
          <Mark />
          <p className="text-lg font-bold text-ink">Keel</p>
        </div>
        <h1 className="mt-4 text-2xl font-bold">Agent console</h1>
        <p className="mt-2 text-sm leading-6 text-muted">
          The shop and the chat widget stay open. This sign-in covers conversations, the inbox, knowledge, and metrics.
        </p>
        {checking ? <p className="mt-6 text-sm text-muted">Checking the console session.</p> : null}
        {checking ? null : (
          <form
            className="mt-6"
            onSubmit={(event) => {
              event.preventDefault();
              setPending(true);
              setError("");
              login(password)
                .then(onSuccess)
                .catch((err: unknown) => {
                  setError(err instanceof Error ? err.message : "Sign-in failed.");
                  setPending(false);
                });
            }}
          >
            <label className="text-sm font-bold" htmlFor="console-password">
              Password
            </label>
            <input
              id="console-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-canvas px-3 py-2 text-sm"
            />
            <button type="submit" disabled={pending} className="mt-4 w-full rounded-lg bg-yellow px-3 py-2 text-sm font-bold text-[#141816] disabled:opacity-60">
              {pending ? "Signing in" : "Sign in"}
            </button>
            {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}
          </form>
        )}
        <p className="mt-6 text-sm leading-6 text-muted">Demo sign-in. The password is marlow-hale and is not a production credential.</p>
      </div>
    </div>
  );
}

function KeyField({ id, value, onChange }: { id: string; value: string; onChange: (value: string) => void }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onChange(draft);
      }}
    >
      <label className="block text-xs text-current/80" htmlFor={id}>
        Session API key
      </label>
      <div className="mt-1 flex gap-2">
        <input
          id={id}
          type="password"
          autoComplete="off"
          value={draft}
          placeholder="sk-ant-… or sk-…"
          onChange={(event) => setDraft(event.target.value)}
          className="w-full rounded-lg border border-line bg-sheet px-2 py-1.5 text-sm text-ink"
        />
        <button type="submit" className="rounded-lg bg-yellow px-2 py-1.5 text-sm font-bold text-[#141816]">
          Use
        </button>
      </div>
      {value ? (
        <button
          type="button"
          className="mt-2 text-xs underline"
          onClick={() => {
            setDraft("");
            onChange("");
          }}
        >
          Clear key
        </button>
      ) : null}
    </form>
  );
}

export function Mark() {
  return (
    <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M5 20h22l-3 5H8L5 20z" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M16 6v14" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}
