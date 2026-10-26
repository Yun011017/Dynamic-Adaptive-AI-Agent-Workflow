"use client";

import { useEffect, useRef, useState } from "react";

const labels = {
  PENDING: "等待 worker",
  RUNNING: "執行中",
  COMPLETED: "已完成",
  FAILED: "執行失敗",
};
const colors = {
  PENDING: "bg-amber-100 text-amber-800",
  RUNNING: "bg-blue-100 text-maker-blue",
  COMPLETED: "bg-emerald-100 text-emerald-800",
  FAILED: "bg-red-100 text-red-800",
};
const blank = { goal: "", context: "", channel: "instagram" };

function Pill({ status }) {
  return (
    <span
      className={`rounded-full px-2.5 py-1 font-mono text-[11px] font-semibold ${colors[status] || "bg-stone-100"}`}
    >
      {labels[status] || status}
    </span>
  );
}
function Field({ label, children }) {
  return (
    <label className="block text-sm font-semibold">
      {label}
      <span className="mt-1.5 block">{children}</span>
    </label>
  );
}

export default function Dashboard() {
  const fallback =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
  const [base, setBase] = useState(fallback);
  const [key, setKey] = useState("");
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState(blank);
  const [showForm, setShowForm] = useState(true);
  const [settings, setSettings] = useState(false);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState(false);
  const resultRef = useRef(null);
  const finished = useRef(new Set());
  const normal = () => base.trim().replace(/\/$/, "");
  const call = async (path, options = {}) => {
    if (!key) throw new Error("請先設定 Development API key。");
    const response = await fetch(`${normal()}${path}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
      },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok)
      throw new Error(body.detail || body.error?.message || "後端請求失敗。");
    return body;
  };
  const loadHistory = async () => {
    const values = await call("/agent/runs");
    setRuns(values);
    setConnection(true);
  };
  useEffect(() => {
    const savedBase = sessionStorage.getItem("agentApiBase"),
      savedKey = sessionStorage.getItem("agentApiKey");
    if (savedBase) setBase(savedBase);
    if (savedKey) setKey(savedKey);
  }, []);
  useEffect(() => {
    if (key) loadHistory().catch(() => setConnection(false));
  }, [key, base]);
  useEffect(() => {
    const active = runs.filter((run) =>
      ["PENDING", "RUNNING"].includes(run.status),
    );
    if (!active.length || !key) return;
    const timer = setInterval(async () => {
      try {
        const values = await Promise.all(
          active.map((run) => call(`/agent/runs/${run.run_id}`)),
        );
        setRuns((all) =>
          all.map(
            (run) => values.find((value) => value.run_id === run.run_id) || run,
          ),
        );
        setConnection(true);
      } catch {
        setConnection(false);
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [runs, key, base]);
  useEffect(() => {
    const run = runs.find((item) => item.run_id === selected);
    if (
      run &&
      ["COMPLETED", "FAILED"].includes(run.status) &&
      !finished.current.has(run.run_id)
    ) {
      finished.current.add(run.run_id);
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [runs, selected]);
  async function save(event) {
    event.preventDefault();
    setError("");
    try {
      const response = await fetch(`${normal()}/health`);
      if (!response.ok) throw new Error();
      sessionStorage.setItem("agentApiBase", normal());
      sessionStorage.setItem("agentApiKey", key);
      setSettings(false);
      setConnection(true);
      await loadHistory();
    } catch {
      setError("無法連線後端，請確認 FastAPI URL。 ");
    }
  }
  async function submit(event) {
    event.preventDefault();
    if (!form.goal.trim()) return setError("請填寫活動目標。");
    setError("");
    try {
      const run = await call("/agent/runs", {
        method: "POST",
        body: JSON.stringify({
          goal: form.goal.trim(),
          context: form.context.trim(),
          constraints: { channel: form.channel },
        }),
      });
      setRuns((all) => [run, ...all]);
      setSelected(run.run_id);
      setForm(blank);
      setShowForm(false);
    } catch (cause) {
      setError(cause.message);
    }
  }
  const current = runs.find((run) => run.run_id === selected);
  return (
    <main className="mx-auto min-h-screen w-[min(1160px,92vw)] py-10 text-maker-ink">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="m-0 font-mono text-xs font-semibold tracking-[.12em] text-maker-blue">
            NTU MAKER · AGENT CONSOLE
          </p>
          <h1 className="mt-2 text-4xl font-semibold">行銷建議工作</h1>
        </div>
        <div className="flex items-center gap-3">
          <span className="font-mono text-xs">
            {connection ? "● 後端已連線" : "● 尚未連線"}
          </span>
          <button
            onClick={() => setSettings(true)}
            className="rounded-xl bg-stone-100 px-4 py-3 font-semibold text-maker-blue"
          >
            連線設定
          </button>
        </div>
      </header>
      <div className="grid gap-5 lg:grid-cols-[.9fr_1.1fr]">
        <section className="rounded-2xl border border-maker-line bg-maker-paper p-6 shadow-panel">
          {showForm ? (
            <>
              <h2 className="mt-0 pb-4 text-xl">新增工作</h2>
              <form onSubmit={submit} className="space-y-5">
                <Field label="活動目標 *">
                  <input
                    className="input"
                    value={form.goal}
                    onChange={(e) => setForm({ ...form, goal: e.target.value })}
                    placeholder="例如：提高新手創客工作坊報名人數"
                  />
                </Field>
                <Field label="活動背景">
                  <textarea
                    className="input min-h-32 resize-y"
                    value={form.context}
                    onChange={(e) =>
                      setForm({ ...form, context: e.target.value })
                    }
                  />
                </Field>
                <Field label="建議渠道">
                  <select
                    className="input"
                    value={form.channel}
                    onChange={(e) =>
                      setForm({ ...form, channel: e.target.value })
                    }
                  >
                    <option value="instagram">Instagram</option>
                    <option value="google_forms">Google Forms</option>
                    <option value="multi_channel">多渠道</option>
                  </select>
                </Field>
                {error && (
                  <p role="alert" className="text-sm text-red-700">
                    {error}
                  </p>
                )}
                <button className="w-full rounded-xl bg-maker-blue px-4 py-3 font-semibold text-white">
                  建立 Agent 工作
                </button>
              </form>
            </>
          ) : (
            <div className="grid min-h-64 place-items-center text-center">
              <div>
                <p className="font-mono text-xs text-maker-blue">WORK QUEUED</p>
                <h2 className="text-2xl">工作已建立</h2>
                <p className="text-maker-muted">
                  結果會顯示在右側歷史紀錄，完成後自動帶你查看。
                </p>
                <button
                  onClick={() => setShowForm(true)}
                  className="mt-3 rounded-xl bg-maker-blue px-4 py-3 font-semibold text-white"
                >
                  建立下一筆工作
                </button>
              </div>
            </div>
          )}
        </section>
        <section className="rounded-2xl border border-maker-line bg-maker-paper p-6 shadow-panel">
          <div className="mb-5 flex items-center justify-between">
            <div>
              <p className="m-0 font-mono text-xs font-semibold tracking-[.12em] text-maker-blue">
                HISTORY
              </p>
              <h2 className="mt-1 text-xl">工作歷史紀錄</h2>
            </div>
            <button
              onClick={() =>
                loadHistory().catch(() => setError("無法更新歷史紀錄。"))
              }
              className="rounded-lg bg-stone-100 px-3 py-2 text-sm font-semibold text-maker-blue"
            >
              重新整理
            </button>
          </div>
          {runs.length ? (
            <ol className="m-0 grid list-none gap-3 p-0">
              {runs.map((run) => (
                <li key={run.run_id}>
                  <button
                    onClick={() => {
                      setSelected(run.run_id);
                      resultRef.current?.scrollIntoView({
                        behavior: "smooth",
                        block: "start",
                      });
                    }}
                    className={`w-full rounded-xl border p-4 text-left ${selected === run.run_id ? "border-[#89a9cc] bg-[#edf3f8]" : "border-maker-line hover:bg-stone-50"}`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <strong className="truncate">
                        {run.input_payload.goal}
                      </strong>
                      <Pill status={run.status} />
                    </span>
                    <small className="mt-1 block font-mono text-xs text-maker-muted">
                      {new Date(run.created_at).toLocaleString("zh-TW")}
                    </small>
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            <p className="py-16 text-center text-maker-muted">尚無工作紀錄</p>
          )}
        </section>
      </div>
      <section
        ref={resultRef}
        className="mt-5 scroll-mt-5 rounded-2xl border border-maker-line bg-maker-paper p-6 shadow-panel"
      >
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="m-0 font-mono text-xs font-semibold tracking-[.12em] text-maker-blue">
              RESULT
            </p>
            <h2 className="mt-1 text-xl">工作詳情</h2>
          </div>
          {current && <Pill status={current.status} />}
        </div>
        {current ? (
          <div className="mt-5">
            <p className="font-mono text-xs text-maker-muted">
              RUN ID · {current.run_id}
            </p>
            {current.status === "FAILED" && (
              <p className="rounded-xl bg-red-50 p-4 text-red-800">
                {current.error_message || "Worker 無法完成工作。"}
              </p>
            )}
            {current.output_payload ? (
              <div className="grid gap-4 md:grid-cols-2">
                <Card
                  title="目標受眾"
                  value={current.output_payload.target_audience}
                />
                <Card
                  title="內容方向"
                  value={current.output_payload.content_direction}
                />
                <Card title="建議依據" value={current.output_payload.reason} />
                <Card
                  title="預期指標"
                  value={(current.output_payload.expected_metrics || []).join(
                    "、",
                  )}
                />
              </div>
            ) : (
              <p className="text-maker-muted">正在等待 worker 處理…</p>
            )}
          </div>
        ) : (
          <p className="py-10 text-center text-maker-muted">
            從歷史紀錄選擇一筆工作查看結果。
          </p>
        )}
      </section>
      {settings && (
        <div className="fixed inset-0 grid place-items-center bg-maker-ink/40 p-4">
          <form
            onSubmit={save}
            className="w-full max-w-lg rounded-2xl bg-maker-paper p-6 shadow-2xl"
          >
            <h2 className="mt-0 text-2xl pb-4">後端連線設定</h2>
            <div className="space-y-4">
              <Field label="FastAPI URL">
                <input
                  className="input"
                  value={base}
                  onChange={(e) => setBase(e.target.value)}
                />
              </Field>
              <Field label="Development API key">
                <input
                  type="password"
                  className="input"
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                />
              </Field>
            </div>
            {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setSettings(false)}
                className="rounded-xl bg-stone-100 px-4 py-3 font-semibold"
              >
                取消
              </button>
              <button className="rounded-xl bg-maker-blue px-4 py-3 font-semibold text-white">
                儲存設定
              </button>
            </div>
          </form>
        </div>
      )}
    </main>
  );
}

function Card({ title, value }) {
  return (
    <article className="rounded-xl border border-maker-line p-4">
      <p className="m-0 font-mono text-xs text-maker-muted">{title}</p>
      <p className="mb-0 mt-2 whitespace-pre-wrap leading-6">{value || "—"}</p>
    </article>
  );
}
