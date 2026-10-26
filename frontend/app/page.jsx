"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Dashboard from "./dashboard";

const STATES = {
  PENDING: ["等待 worker", "bg-amber-100 text-amber-800"],
  RUNNING: ["執行中", "bg-blue-100 text-maker-blue"],
  COMPLETED: ["已完成", "bg-emerald-100 text-emerald-800"],
  FAILED: ["執行失敗", "bg-red-100 text-red-800"],
};

function Icon({ children, className = "" }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className={`h-5 w-5 fill-none stroke-current stroke-[1.8] ${className}`}
    >
      {children}
    </svg>
  );
}

function Status({ value }) {
  const [label, color] = STATES[value] || [
    value,
    "bg-stone-200 text-stone-700",
  ];
  return (
    <span
      className={`rounded-full px-2.5 py-1 font-mono text-[11px] font-semibold ${color}`}
    >
      {label}
    </span>
  );
}

function Field({ label, required, children }) {
  return (
    <label className="block text-sm font-semibold text-maker-ink">
      {label}
      {required && <span className="ml-1 text-maker-red">*</span>}
      <span className="mt-1.5 block">{children}</span>
    </label>
  );
}

function PanelTitle({ eyebrow, title, badge }) {
  return (
    <div className="mb-6 flex items-center justify-between">
      <div>
        <p className="mb-1 font-mono text-xs font-semibold tracking-[.12em] text-maker-blue">
          {eyebrow}
        </p>
        <h3 className="m-0 text-xl font-semibold">{title}</h3>
      </div>
      <span className="grid min-w-9 place-items-center rounded-xl bg-[#e7eef7] px-2 py-2 font-mono text-xs font-semibold text-maker-blue">
        {badge}
      </span>
    </div>
  );
}

function ResultCard({ label, value }) {
  return (
    <div className="rounded-xl border border-maker-line bg-maker-paper p-4">
      <p className="m-0 font-mono text-xs font-semibold tracking-[.08em] text-maker-muted">
        {label}
      </p>
      <p className="mb-0 mt-2 whitespace-pre-wrap text-sm leading-6">
        {value || "—"}
      </p>
    </div>
  );
}

function RunResult({ run }) {
  const output = run.output_payload;
  const timestamp = run.finished_at || run.started_at || run.created_at;
  return (
    <div>
      <div className="grid gap-4 border-b border-maker-line pb-5 sm:grid-cols-[2fr_1fr_1fr]">
        <Meta label="RUN ID" value={run.run_id} mono />
        <Meta
          label="模型"
          value={`${run.agent_provider} / ${run.agent_model}`}
        />
        <Meta
          label="更新時間"
          value={timestamp ? new Date(timestamp).toLocaleString("zh-TW") : "—"}
        />
      </div>
      {run.status === "FAILED" && (
        <p
          role="alert"
          className="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-800"
        >
          {run.error_message || "Worker 無法完成這筆工作。"}
        </p>
      )}
      {output && (
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <ResultCard label="目標受眾" value={output.target_audience} />
          <ResultCard label="內容方向" value={output.content_direction} />
          <ResultCard label="建議依據" value={output.reason} />
          <div className="rounded-xl border border-maker-line bg-maker-paper p-4">
            <p className="m-0 font-mono text-xs font-semibold tracking-[.08em] text-maker-muted">
              預期指標
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {(output.expected_metrics || []).map((item) => (
                <span
                  key={item}
                  className="rounded-full bg-[#e7eef7] px-2.5 py-1 text-xs font-semibold text-maker-blue"
                >
                  {item}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Meta({ label, value, mono }) {
  return (
    <div>
      <p className="mb-1 font-mono text-[11px] font-semibold tracking-[.08em] text-maker-muted">
        {label}
      </p>
      <p
        className={`m-0 break-all text-sm font-semibold ${mono ? "font-mono text-xs" : ""}`}
      >
        {value}
      </p>
    </div>
  );
}

export default function Home() {
  return <Dashboard />;

  const fallbackBase =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
  const [baseUrl, setBaseUrl] = useState(fallbackBase);
  const [apiKey, setApiKey] = useState("");
  const [connection, setConnection] = useState("idle");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [runs, setRuns] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [form, setForm] = useState({
    goal: "",
    context: "",
    channel: "instagram",
  });
  const [error, setError] = useState("");
  const [settingsError, setSettingsError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const viewedFinishedRuns = useRef(new Set());
  const selected = useMemo(
    () => runs.find((run) => run.run_id === selectedId),
    [runs, selectedId],
  );
  const normalizedBase = () => baseUrl.trim().replace(/\/$/, "");

  async function health(target = normalizedBase()) {
    const response = await fetch(`${target}/health`);
    if (!response.ok) throw new Error("健康檢查失敗。");
  }

  async function request(path, options = {}) {
    if (!apiKey) throw new Error("請先設定 Development API key。");
    const response = await fetch(`${normalizedBase()}${path}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        ...options.headers,
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok)
      throw new Error(
        payload.detail || payload.error?.message || "無法完成後端請求。",
      );
    return payload;
  }

  useEffect(() => {
    const savedBase = window.sessionStorage.getItem("agentApiBase");
    const savedKey = window.sessionStorage.getItem("agentApiKey");
    if (savedBase) setBaseUrl(savedBase);
    if (savedKey) setApiKey(savedKey);
  }, []);

  useEffect(() => {
    health()
      .then(() => setConnection("online"))
      .catch(() => setConnection("offline"));
  }, [baseUrl]);

  useEffect(() => {
    const active = runs.filter((run) =>
      ["PENDING", "RUNNING"].includes(run.status),
    );
    if (!active.length || !apiKey) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const updates = await Promise.all(
          active.map((run) => request(`/agent/runs/${run.run_id}`)),
        );
        setRuns((current) =>
          current.map(
            (run) =>
              updates.find((update) => update.run_id === run.run_id) || run,
          ),
        );
        setConnection("online");
      } catch {
        setConnection("offline");
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [runs, apiKey, baseUrl]);

  useEffect(() => {
    if (
      !selected ||
      !["COMPLETED", "FAILED"].includes(selected.status) ||
      viewedFinishedRuns.current.has(selected.run_id)
    )
      return;
    viewedFinishedRuns.current.add(selected.run_id);
    document
      .querySelector("main > section:last-of-type")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [selected]);

  async function submit(event) {
    event.preventDefault();
    if (!form.goal.trim()) {
      setError("請填寫活動目標。");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      const run = await request("/agent/runs", {
        method: "POST",
        body: JSON.stringify({
          goal: form.goal.trim(),
          context: form.context.trim(),
          constraints: { channel: form.channel },
        }),
      });
      setRuns((current) => [run, ...current]);
      setSelectedId(run.run_id);
      setConnection("online");
      setForm({ goal: "", context: "", channel: "instagram" });
      window.setTimeout(
        () =>
          document.querySelector("input[placeholder^='例如：提高']")?.focus(),
        0,
      );
    } catch (cause) {
      setError(cause.message);
      setConnection("offline");
    } finally {
      setSubmitting(false);
    }
  }

  async function saveSettings(event) {
    event.preventDefault();
    setSettingsError("");
    try {
      const target = normalizedBase();
      await health(target);
      window.sessionStorage.setItem("agentApiBase", target);
      window.sessionStorage.setItem("agentApiKey", apiKey);
      setBaseUrl(target);
      setConnection("online");
      setSettingsOpen(false);
    } catch {
      setConnection("offline");
      setSettingsError("無法連線後端，請確認 FastAPI URL。");
    }
  }

  return (
    <>
      <a
        href="#main"
        className="absolute left-4 top-[-5rem] z-50 rounded bg-maker-ink px-4 py-2 text-white focus:top-4"
      >
        跳至主要內容
      </a>
      <header className="flex items-center justify-between gap-4 border-b border-maker-line bg-maker-paper/90 px-[max(5vw,1.5rem)] py-4 backdrop-blur">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-maker-blue text-white">
            <Icon>
              <path d="M12 3 4 7.5v9L12 21l8-4.5v-9L12 3Z" />
              <path d="m8.5 12 2.3 2.3 4.7-4.7" />
            </Icon>
          </span>
          <div>
            <p className="m-0 font-mono text-[11px] font-semibold tracking-[.12em] text-maker-blue">
              NTU MAKER
            </p>
            <h1 className="m-0 text-base font-semibold">
              Agent Workflow Console
            </h1>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span
            role="status"
            className="hidden items-center gap-2 font-mono text-xs sm:flex"
          >
            <span
              className={`h-2 w-2 rounded-full ${connection === "online" ? "bg-emerald-500" : "bg-stone-400"}`}
            />
            {connection === "online" ? "後端已連線" : "尚未連線"}
          </span>
          <button
            onClick={() => setSettingsOpen(true)}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-stone-100 px-4 py-2 text-sm font-semibold text-maker-blue transition hover:bg-stone-200"
          >
            <Icon>
              <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" />
              <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.1 2.1-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56V20.3h-3v-.1A1.7 1.7 0 0 0 10.7 18.6a1.7 1.7 0 0 0-1.88.34l-.06.06-2.1-2.1.06-.06A1.7 1.7 0 0 0 7.06 15a1.7 1.7 0 0 0-1.56-1.03H5.4v-3h.1A1.7 1.7 0 0 0 7.06 9.94a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.1-2.1.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.03-1.56V4.6h3v.14a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.1 2.1-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.56 1.03h.1v3h-.1A1.7 1.7 0 0 0 19.4 15Z" />
            </Icon>
            連線設定
          </button>
        </div>
      </header>
      <main id="main" className="mx-auto w-[min(1160px,90vw)] py-12 sm:py-16">
        <section className="mb-8 max-w-2xl">
          <p className="mb-2 font-mono text-xs font-semibold tracking-[.12em] text-maker-red">
            AGENT RUNS
          </p>
          <h2 className="m-0 text-4xl font-semibold tracking-[-.045em] sm:text-5xl">
            建立行銷建議工作
          </h2>
          <p className="mt-4 text-lg text-maker-muted">
            送出後由背景 worker 處理。這裡會自動更新工作狀態與模型建議。
          </p>
        </section>
        <div className="grid gap-5 lg:grid-cols-[1.05fr_.95fr]">
          <section className="rounded-[1.25rem] border border-maker-line bg-maker-paper p-6 shadow-panel">
            <PanelTitle eyebrow="NEW RUN" title="新增工作" badge="01" />
            <form onSubmit={submit} className="space-y-5">
              <Field label="活動目標" required>
                <input
                  value={form.goal}
                  onChange={(event) =>
                    setForm({ ...form, goal: event.target.value })
                  }
                  maxLength="500"
                  placeholder="例如：提高新手創客工作坊報名人數"
                  className="input"
                />
              </Field>
              <Field label="活動背景">
                <textarea
                  value={form.context}
                  onChange={(event) =>
                    setForm({ ...form, context: event.target.value })
                  }
                  rows="5"
                  maxLength="4000"
                  placeholder="例如：面向第一次接觸自造的學生，活動將在下週舉行。"
                  className="input min-h-28 resize-y"
                />
              </Field>
              <Field label="建議渠道">
                <select
                  value={form.channel}
                  onChange={(event) =>
                    setForm({ ...form, channel: event.target.value })
                  }
                  className="input"
                >
                  <option value="instagram">Instagram</option>
                  <option value="google_forms">Google Forms</option>
                  <option value="multi_channel">多渠道</option>
                </select>
              </Field>
              {error && (
                <p role="alert" className="-mt-2 text-sm text-red-700">
                  {error}
                </p>
              )}
              <button
                disabled={submitting}
                className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-maker-blue px-4 py-3 font-semibold text-white shadow-lg shadow-maker-blue/20 transition hover:bg-[#234a7c] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Icon>
                  <path d="m5 12 5 5L20 7" />
                </Icon>
                {submitting ? "正在建立工作…" : "建立 Agent 工作"}
              </button>
            </form>
          </section>
          <section className="rounded-[1.25rem] border border-maker-line bg-maker-paper p-6 shadow-panel">
            <PanelTitle
              eyebrow="ACTIVITY"
              title="本次工作階段"
              badge={String(runs.length)}
            />
            {runs.length === 0 ? (
              <div className="grid min-h-64 place-items-center text-center text-maker-muted">
                <div>
                  <Icon className="mx-auto h-8 w-8 text-maker-blue">
                    <path d="M4 5h16v14H4z" />
                    <path d="M8 9h8M8 13h5" />
                  </Icon>
                  <p className="mb-1 mt-3 font-semibold text-maker-ink">
                    尚未建立工作
                  </p>
                  <p className="m-0 text-sm">
                    先完成連線設定，再送出第一筆目標。
                  </p>
                </div>
              </div>
            ) : (
              <ol className="m-0 grid list-none gap-3 p-0" aria-live="polite">
                {runs.map((run) => (
                  <li key={run.run_id}>
                    <button
                      onClick={() => setSelectedId(run.run_id)}
                      className={`w-full rounded-xl border p-4 text-left transition ${selectedId === run.run_id ? "border-[#89a9cc] bg-[#edf3f8]" : "border-transparent bg-maker-paper hover:border-maker-line"}`}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <strong className="truncate">
                          {run.input_payload.goal}
                        </strong>
                        <Status value={run.status} />
                      </span>
                      <small className="mt-1 block font-mono text-xs text-maker-muted">
                        {run.run_id}
                      </small>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
        <section className="mt-5 rounded-[1.25rem] border border-maker-line bg-maker-paper p-6 shadow-panel">
          <div className="mb-6 flex items-center justify-between gap-4">
            <div>
              <p className="mb-1 font-mono text-xs font-semibold tracking-[.12em] text-maker-blue">
                RESULT
              </p>
              <h3 className="m-0 text-xl font-semibold">工作詳情</h3>
            </div>
            <Status value={selected?.status || "等待建立"} />
          </div>
          {selected ? (
            <RunResult run={selected} />
          ) : (
            <p className="py-10 text-center text-maker-muted">
              選擇一筆工作後，這裡會顯示狀態、模型建議與可追蹤的 run ID。
            </p>
          )}
        </section>
      </main>
      {settingsOpen && (
        <div
          className="fixed inset-0 z-40 grid place-items-center bg-maker-ink/40 p-4"
          role="presentation"
        >
          <form
            onSubmit={saveSettings}
            className="w-full max-w-lg rounded-2xl border border-maker-line bg-maker-paper p-6 shadow-2xl"
            aria-labelledby="settings-title"
          >
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <p className="mb-1 font-mono text-xs font-semibold tracking-[.12em] text-maker-blue">
                  CONNECTION
                </p>
                <h2 id="settings-title" className="m-0 text-2xl font-semibold">
                  後端連線設定
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setSettingsOpen(false)}
                aria-label="關閉設定"
                className="grid h-11 w-11 place-items-center rounded-xl bg-stone-100 text-maker-blue hover:bg-stone-200"
              >
                <Icon>
                  <path d="m6 6 12 12M18 6 6 18" />
                </Icon>
              </button>
            </div>
            <p className="mb-5 text-sm text-maker-muted">
              僅用於目前瀏覽器分頁，不會儲存到資料庫或 Git。
            </p>
            <div className="space-y-4">
              <Field label="FastAPI URL">
                <input
                  type="url"
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                  required
                  className="input"
                />
              </Field>
              <Field label="Development API key">
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  autoComplete="off"
                  required
                  placeholder="貼上 PLATFORM_API_KEY"
                  className="input"
                />
                <p className="mt-1 text-xs text-maker-muted">
                  可在後端 <code>backend/.env</code> 找到。
                </p>
              </Field>
            </div>
            {settingsError && (
              <p role="alert" className="mt-4 text-sm text-red-700">
                {settingsError}
              </p>
            )}
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setSettingsOpen(false)}
                className="min-h-11 rounded-xl bg-stone-100 px-4 py-2 font-semibold text-maker-blue hover:bg-stone-200"
              >
                取消
              </button>
              <button className="min-h-11 rounded-xl bg-maker-blue px-4 py-2 font-semibold text-white hover:bg-[#234a7c]">
                儲存設定
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
