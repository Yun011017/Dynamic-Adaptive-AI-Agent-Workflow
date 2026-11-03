"use client";

import { useEffect, useRef, useState } from "react";

const labels = {
  PENDING: "等待 worker",
  RUNNING: "執行中",
  COMPLETED: "已完成",
  FAILED: "執行失敗",
  DRAFT: "待編修",
  SCHEDULED: "已排程",
  SUPERSEDED: "已由新版取代",
};
const colors = {
  PENDING: "bg-amber-100 text-amber-800",
  RUNNING: "bg-blue-100 text-maker-blue",
  COMPLETED: "bg-emerald-100 text-emerald-800",
  FAILED: "bg-red-100 text-red-800",
  DRAFT: "bg-stone-100 text-stone-700",
  SCHEDULED: "bg-orange-100 text-orange-900",
  SUPERSEDED: "bg-stone-100 text-stone-500",
};
const blank = { goal: "", context: "", channel: "instagram" };
const blankDraft = {
  title: "",
  caption: "",
  hashtags: "",
  imageRequirement: "",
  imageUrls: "",
  scheduledAt: "",
  scheduleRequested: false,
  carousel: true,
};

type Strategy = {
  id: number;
  goal_id: number;
  version: number;
  content: string;
  rationale: string | null;
};

type Goal = {
  id: number;
  title: string;
};

type ContentDraft = {
  id: number;
  execution_id: number;
  status: string;
  draft_version: number;
  payload: {
    channel?: "instagram";
    title?: string;
    caption?: string;
    hashtags?: string[];
    image_requirements?: string[];
    image_urls?: string[];
    carousel?: boolean;
    scheduled_at?: string | null;
    schedule_requested?: boolean;
    strategy_id?: number;
    proposal_version?: number;
  };
};

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

function proposalVersion(draft: ContentDraft) {
  const major = draft.payload.proposal_version;
  if (!major) return `舊資料 v${draft.draft_version}`;
  return `v${major}.${draft.draft_version}`;
}

export default function Dashboard() {
  const fallback =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
  const [base, setBase] = useState(fallback);
  const [key, setKey] = useState("");
  const [runs, setRuns] = useState([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [drafts, setDrafts] = useState<ContentDraft[]>([]);
  const [scheduledDrafts, setScheduledDrafts] = useState<ContentDraft[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<number | null>(null);
  const [draftForm, setDraftForm] = useState(blankDraft);
  const [editingDraft, setEditingDraft] = useState<ContentDraft | null>(null);
  const [draftSaving, setDraftSaving] = useState(false);
  const [scheduleSaving, setScheduleSaving] = useState<number | null>(null);
  const [draftGenerationRun, setDraftGenerationRun] = useState<string | null>(null);
  const [draftGenerating, setDraftGenerating] = useState(false);
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
    const [values, strategyValues, goalValues] = await Promise.all([
      call("/agent/runs"),
      call("/strategies"),
      call("/goals"),
    ]);
    setRuns(values);
    setStrategies(strategyValues);
    setGoals(goalValues);
    setSelectedStrategy((selected) => selected ?? strategyValues[0]?.id ?? null);
    setConnection(true);
  };
  const loadScheduledDrafts = async () => {
    if (!key) {
      setScheduledDrafts([]);
      return;
    }
    setScheduledDrafts(await call("/content-drafts/scheduled"));
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
    if (!key || !selectedStrategy) {
      setDrafts([]);
      return;
    }
    call(`/strategies/${selectedStrategy}/content-drafts`)
      .then(setDrafts)
      .catch(() => setDrafts([]));
  }, [selectedStrategy, key, base]);
  useEffect(() => {
    loadScheduledDrafts().catch(() => setScheduledDrafts([]));
  }, [key, base]);
  useEffect(() => {
    if (!draftGenerationRun || !selectedStrategy) return;
    const run = runs.find((item) => item.run_id === draftGenerationRun);
    if (run?.status === "COMPLETED") {
      call(`/strategies/${selectedStrategy}/content-drafts`)
        .then(setDrafts)
        .catch(() => setError("草稿已產生，但無法更新草稿清單。"));
      setDraftGenerating(false);
      setDraftGenerationRun(null);
    }
    if (run?.status === "FAILED") {
      setDraftGenerating(false);
      setDraftGenerationRun(null);
      setError("內容草稿產生失敗，請檢查 worker 後再重試。");
    }
  }, [runs, draftGenerationRun, selectedStrategy, key, base]);
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
  function openRun(run) {
    setSelected(run.run_id);
    const strategyId = run.output_payload?.strategy_id;
    if (typeof strategyId === "number") {
      setSelectedStrategy(strategyId);
      setEditingDraft(null);
      setDraftForm(blankDraft);
    }
    resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  async function saveDraft(scheduleRequested = draftForm.scheduleRequested) {
    if (!selectedStrategy) return setError("請先選擇一筆 Strategy。");
    if (!draftForm.title.trim()) return setError("請填寫提案名稱。");
    if (!draftForm.caption.trim()) return setError("請填寫貼文文案。");
    if (scheduleRequested && !draftForm.scheduledAt) {
      return setError("建立排程前，請先設定預計發布時間。");
    }
    setDraftSaving(true);
    setError("");
    try {
      const path = editingDraft
        ? `/content-drafts/${editingDraft.id}/versions`
        : `/strategies/${selectedStrategy}/content-drafts`;
      const draft = await call(path, {
        method: "POST",
        body: JSON.stringify({
          channel: "instagram",
          title: draftForm.title.trim(),
          caption: draftForm.caption.trim(),
          hashtags: draftForm.hashtags.split(/[\s,，]+/).filter(Boolean),
          image_requirements: draftForm.imageRequirement
            .split("\n")
            .filter((value) => value.trim()),
          image_urls: draftForm.imageUrls
            .split("\n")
            .filter((value) => value.trim()),
          carousel: draftForm.carousel,
          scheduled_at: draftForm.scheduledAt
            ? new Date(draftForm.scheduledAt).toISOString()
            : null,
          schedule_requested: scheduleRequested,
        }),
      });
      if (editingDraft) {
        setDrafts((all) => [
          draft,
          ...all.map((item) =>
            item.id === editingDraft.id ? { ...item, status: "SUPERSEDED" } : item,
          ),
        ]);
        setEditingDraft(draft);
        setDraftForm((form) => ({ ...form, scheduleRequested }));
      } else {
        setDrafts((all) => [draft, ...all.filter((item) => item.id !== draft.id)]);
        setDraftForm(blankDraft);
      }
      loadScheduledDrafts().catch(() => setScheduledDrafts([]));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "無法建立內容草稿。");
    } finally {
      setDraftSaving(false);
    }
  }
  async function generateDraft() {
    if (!selectedStrategy) return setError("請先選擇一筆 Strategy。");
    setDraftGenerating(true);
    setError("");
    try {
      const run = await call(`/strategies/${selectedStrategy}/content-draft-runs`, {
        method: "POST",
        body: JSON.stringify({
          channel: "instagram",
          content_format: draftForm.carousel ? "carousel" : "single",
          scheduled_at: draftForm.scheduledAt
            ? new Date(draftForm.scheduledAt).toISOString()
            : null,
          schedule_requested: draftForm.scheduleRequested,
        }),
      });
      setRuns((all) => [run, ...all]);
      setDraftGenerationRun(run.run_id);
    } catch (cause) {
      setDraftGenerating(false);
      setError(cause instanceof Error ? cause.message : "無法建立內容草稿工作。");
    }
  }
  function beginRevision(draft: ContentDraft) {
    // A publishing plan belongs to the proposal across revisions. Older rows
    // may predate that plan, so show the newest saved time rather than making
    // it appear to disappear when the user only opens another version.
    const scheduledSource = draft.payload.scheduled_at
      ? draft
      : drafts
          .filter((item) => item.execution_id === draft.execution_id && item.payload.scheduled_at)
          .sort((a, b) => b.draft_version - a.draft_version)[0];
    const scheduledAt = scheduledSource?.payload.scheduled_at
      ? new Date(new Date(scheduledSource.payload.scheduled_at).getTime() - new Date().getTimezoneOffset() * 60_000)
          .toISOString()
          .slice(0, 16)
      : "";
    setEditingDraft(draft);
    setDraftForm({
      title: draft.payload.title || "",
      caption: draft.payload.caption || "",
      hashtags: (draft.payload.hashtags || []).join(", "),
      imageRequirement: (draft.payload.image_requirements || []).join("\n"),
      imageUrls: (draft.payload.image_urls || []).join("\n"),
      scheduledAt,
      scheduleRequested: Boolean(draft.payload.schedule_requested),
      carousel: Boolean(draft.payload.carousel),
    });
    document.getElementById("draft-form")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  async function cancelSchedule(draft: ContentDraft) {
    setScheduleSaving(draft.id);
    setError("");
    try {
      const revised = await call(`/content-drafts/${draft.id}/versions`, {
        method: "POST",
        body: JSON.stringify({
          channel: draft.payload.channel || "instagram",
          title: draft.payload.title || "未命名內容提案",
          caption: draft.payload.caption || "未命名內容",
          hashtags: draft.payload.hashtags || [],
          image_requirements: draft.payload.image_requirements || [],
          image_urls: draft.payload.image_urls || [],
          carousel: Boolean(draft.payload.carousel),
          scheduled_at: null,
          schedule_requested: false,
        }),
      });
      setDrafts((all) => [
        revised,
        ...all.map((item) =>
          item.id === draft.id ? { ...item, status: "SUPERSEDED" } : item,
        ),
      ]);
      if (editingDraft?.id === draft.id) setEditingDraft(revised);
      loadScheduledDrafts().catch(() => setScheduledDrafts([]));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "無法取消排程。");
    } finally {
      setScheduleSaving(null);
    }
  }
  async function addToSchedule(draft: ContentDraft) {
    if (!draft.payload.scheduled_at) return;
    setScheduleSaving(draft.id);
    setError("");
    try {
      const revised = await call(`/content-drafts/${draft.id}/versions`, {
        method: "POST",
        body: JSON.stringify({
          channel: draft.payload.channel || "instagram",
          title: draft.payload.title || "未命名內容提案",
          caption: draft.payload.caption || "未命名內容",
          hashtags: draft.payload.hashtags || [],
          image_requirements: draft.payload.image_requirements || [],
          image_urls: draft.payload.image_urls || [],
          carousel: Boolean(draft.payload.carousel),
          scheduled_at: draft.payload.scheduled_at,
          schedule_requested: true,
        }),
      });
      setDrafts((all) => [
        revised,
        ...all.map((item) =>
          item.id === draft.id ? { ...item, status: "SUPERSEDED" } : item,
        ),
      ]);
      if (editingDraft?.id === draft.id) setEditingDraft(revised);
      loadScheduledDrafts().catch(() => setScheduledDrafts([]));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "無法加入排程。");
    } finally {
      setScheduleSaving(null);
    }
  }
  function openScheduledDraft(draft: ContentDraft) {
    const strategyId = draft.payload.strategy_id;
    if (typeof strategyId === "number") setSelectedStrategy(strategyId);
    beginRevision(draft);
  }
  const current = runs.find((run) => run.run_id === selected);
  const strategyRuns = runs.filter(
    (run) => run.input_payload.job_type !== "CONTENT_DRAFT",
  );
  const activeDrafts = drafts.filter((draft) => !["SUPERSEDED", "EXECUTING", "SUCCEEDED"].includes(draft.status));
  const revisionHistory = editingDraft
    ? drafts
        .filter((draft) => draft.execution_id === editingDraft.execution_id)
        .sort((a, b) => b.draft_version - a.draft_version)
    : [];
  const hasFutureScheduleTime = Boolean(draftForm.scheduledAt)
    && new Date(draftForm.scheduledAt).getTime() > Date.now();
  const draftImageRequirements = draftForm.imageRequirement
    .split("\n")
    .filter((value) => value.trim());
  const draftImageUrls = draftForm.imageUrls
    .split("\n")
    .filter((value) => value.trim());
  const scheduleMissing = [
    !draftForm.title.trim() && "提案名稱",
    !draftForm.caption.trim() && "Instagram 文案",
    !hasFutureScheduleTime && "未來的發布時間",
    draftForm.carousel && draftImageRequirements.length < 2 && "至少兩項輪播素材需求",
    draftImageUrls.some((url) => !url.startsWith("https://")) && "有效的公開 HTTPS 圖片網址",
    draftForm.carousel && draftImageUrls.length > 0 && draftImageUrls.length < 2 && "至少兩張輪播圖片網址",
  ].filter(Boolean) as string[];
  const canCreateSchedule = scheduleMissing.length === 0;
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
                STRATEGY RUNS
              </p>
              <h2 className="mt-1 text-xl">策略工作紀錄</h2>
              <p className="mb-0 mt-1 text-sm text-maker-muted">
                選擇一筆完成的策略工作查看分析結果；內容草稿會顯示在下方。
              </p>
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
          {strategyRuns.length ? (
            <ol className="m-0 grid max-h-[34rem] list-none gap-3 overflow-y-auto pr-2 p-0">
              {strategyRuns.map((run) => (
                <li key={run.run_id}>
                  <button
                    onClick={() => openRun(run)}
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
            <p className="py-16 text-center text-maker-muted">尚無策略工作紀錄</p>
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
            {current.output_payload?.job_type === "CONTENT_DRAFT" ? (
              <div className="rounded-xl border border-maker-line p-4">
                <p className="m-0 font-mono text-xs text-maker-muted">CONTENT PROPOSAL READY</p>
                <p className="mb-0 mt-2 leading-6">
                  已建立 Strategy v{current.output_payload.strategy_version} 的內容提案；請到下方查看、修改素材需求與設定排程。
                </p>
              </div>
            ) : current.output_payload ? (
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
      <section
        id="content-drafts"
        className="mt-5 scroll-mt-5 rounded-2xl border border-maker-line bg-maker-paper p-6 shadow-panel"
      >
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="m-0 font-mono text-xs font-semibold tracking-[.12em] text-maker-blue">
              CONTENT DRAFT
            </p>
            <h2 className="mt-1 text-xl">Instagram 內容提案</h2>
            <p className="mb-0 text-sm text-maker-muted">
              發布時間只是規劃；需明確加入排程，尚不會發布到 Instagram。
            </p>
          </div>
          <label className="min-w-56 text-sm font-semibold">
            選擇 Strategy
            <select
              className="input mt-1.5"
              value={selectedStrategy ?? ""}
              onChange={(event) =>
                setSelectedStrategy(event.target.value ? Number(event.target.value) : null)
              }
            >
              {!strategies.length && <option value="">尚無可用 Strategy</option>}
              {strategies.map((strategy) => (
                <option key={strategy.id} value={strategy.id}>
                  {goals.find((goal) => goal.id === strategy.goal_id)?.title || `Goal ${strategy.goal_id}`} · v{strategy.version}
                </option>
              ))}
            </select>
          </label>
        </div>
        {selectedStrategy ? (
          <>
            <div className="mt-6 grid gap-6 lg:grid-cols-[1.05fr_.95fr]">
            <form id="draft-form" onSubmit={(event) => { event.preventDefault(); saveDraft(); }} className="space-y-4 rounded-xl border border-maker-line p-5">
              <div className="flex items-center justify-between gap-3">
                <h3 className="m-0 text-lg">{editingDraft ? `修改內容提案 ${proposalVersion(editingDraft)}` : "新增內容提案"}</h3>
                {editingDraft && (
                  <button
                    type="button"
                    onClick={() => { setEditingDraft(null); setDraftForm(blankDraft); }}
                    className="rounded-lg bg-stone-100 px-3 py-2 text-sm font-semibold text-maker-blue"
                  >
                    取消修改
                  </button>
                )}
              </div>
              {editingDraft && revisionHistory.length > 1 && (
                <Field label="版本歷史">
                  <select
                    className="input"
                    value={editingDraft.id}
                    onChange={(event) => {
                      const version = drafts.find((draft) => draft.id === Number(event.target.value));
                      if (version) beginRevision(version);
                    }}
                  >
                    {revisionHistory.map((draft) => (
                      <option key={draft.id} value={draft.id}>
                        {proposalVersion(draft)}{draft.id === editingDraft.id ? "（目前檢視）" : ""}
                      </option>
                    ))}
                  </select>
                  <small className="mt-1 block text-maker-muted">
                    選擇舊版本後儲存，會建立一個新的最新版本，不會覆寫歷史。
                  </small>
                </Field>
              )}
              <label className="flex items-start gap-3 rounded-xl border border-maker-line p-4 text-sm">
                <input
                  type="checkbox"
                  checked={draftForm.carousel}
                  onChange={(event) =>
                    setDraftForm({ ...draftForm, carousel: event.target.checked })
                  }
                  className="mt-1 h-4 w-4 accent-[#3265a8]"
                />
                <span>
                  <strong className="block">輪播貼文</strong>
                  <span className="mt-1 block text-maker-muted">
                    輪播至少需要兩項素材需求；取消勾選則建立單張貼文草稿。
                  </span>
                </span>
              </label>
              <Field label="預計發布時間（選填）">
                <input
                  type="datetime-local"
                  className="input"
                  min={new Date(Date.now() - new Date().getTimezoneOffset() * 60_000)
                    .toISOString()
                    .slice(0, 16)}
                  value={draftForm.scheduledAt}
                  onChange={(event) => setDraftForm({ ...draftForm, scheduledAt: event.target.value })}
                />
                <small className="mt-1 block text-maker-muted">
                  可先保存發布規劃；建立排程時必須選擇未來時間。
                </small>
                {draftForm.scheduledAt && !hasFutureScheduleTime && (
                  <small className="mt-1 block font-semibold text-red-700">
                    排程時間必須晚於目前時間。
                  </small>
                )}
              </Field>
              {!editingDraft && (
                <div className="rounded-xl bg-[#edf3f8] p-4">
                  <p className="m-0 text-sm font-semibold text-maker-blue">由 Agent 自動產生內容提案</p>
                  <p className="mb-3 mt-1 text-sm text-maker-muted">
                    會依上方貼文形式與發布規劃建立文案、hashtags 與素材需求；不會虛構圖片網址或直接發布。
                  </p>
                  <button
                    type="button"
                    disabled={draftGenerating}
                    onClick={generateDraft}
                    className="rounded-lg bg-maker-blue px-3 py-2 text-sm font-semibold text-white transition hover:bg-[#244e83] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {draftGenerating
                      ? "Agent 提案產生中…"
                      : draftForm.carousel
                        ? "由 Agent 產生輪播提案"
                        : "由 Agent 產生單張提案"}
                  </button>
                </div>
              )}
              <Field label="提案名稱 *">
                <input
                  className="input"
                  value={draftForm.title}
                  onChange={(event) =>
                    setDraftForm({ ...draftForm, title: event.target.value })
                  }
                  placeholder="例如：新手零基礎體驗輪播"
                />
              </Field>
              <Field label="Instagram 文案 *">
                <textarea
                  className="input min-h-32 resize-y"
                  value={draftForm.caption}
                  onChange={(event) => setDraftForm({ ...draftForm, caption: event.target.value })}
                  placeholder="輸入貼文主文，不必先加上 hashtag。"
                />
              </Field>
              <Field label="Hashtags">
                <input
                  className="input"
                  value={draftForm.hashtags}
                  onChange={(event) => setDraftForm({ ...draftForm, hashtags: event.target.value })}
                  placeholder="NTUMaker, Arduino, 創客"
                />
              </Field>
              <Field label="素材需求（每行一項）">
                <textarea
                  className="input min-h-24 resize-y"
                  value={draftForm.imageRequirement}
                  onChange={(event) => setDraftForm({ ...draftForm, imageRequirement: event.target.value })}
                  placeholder="封面：1080×1080，學生展示實作成品"
                />
              </Field>
              <Field label="公開圖片網址（每行一個）">
                <textarea
                  className="input min-h-20 resize-y"
                  value={draftForm.imageUrls}
                  onChange={(event) => setDraftForm({ ...draftForm, imageUrls: event.target.value })}
                  placeholder="https://example.com/image.jpg"
                />
              </Field>
              <button
                disabled={draftSaving}
                className="w-full rounded-xl bg-maker-blue px-4 py-3 font-semibold text-white transition hover:bg-[#244e83] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {draftSaving ? "儲存提案中…" : editingDraft ? "建立新版本" : "儲存內容提案"}
              </button>
              {editingDraft && (
                <button
                  type="button"
                  disabled={draftSaving || !canCreateSchedule}
                  onClick={() => saveDraft(true)}
                  className="w-full rounded-xl bg-orange-700 px-4 py-3 font-semibold text-white transition hover:bg-orange-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {draftSaving ? "建立排程中…" : "建立排程"}
                </button>
              )}
              {editingDraft && !canCreateSchedule && (
                <p className="m-0 text-center text-sm text-maker-muted">
                  建立排程前請完成：{scheduleMissing.join("、")}
                </p>
              )}
              {editingDraft?.status === "SCHEDULED" && (
                <button
                  type="button"
                  disabled={scheduleSaving === editingDraft.id}
                  onClick={() => cancelSchedule(editingDraft)}
                  className="w-full rounded-xl border border-maker-line px-4 py-3 font-semibold text-maker-muted transition hover:bg-stone-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {scheduleSaving === editingDraft.id ? "取消排程中…" : "取消排程"}
                </button>
              )}
            </form>
            <div className="rounded-xl border border-maker-line p-5">
              <h3 className="m-0 text-lg">此 Strategy 的內容提案</h3>
              {activeDrafts.length ? (
                <ol className="mt-4 grid max-h-[34rem] list-none gap-3 overflow-y-auto pr-2 p-0">
                  {activeDrafts.map((draft) => (
                    <li key={draft.id} className="rounded-xl border border-maker-line p-4">
                      <button
                        type="button"
                        onClick={() => beginRevision(draft)}
                        className="w-full text-left"
                      >
                        <span className="flex flex-wrap items-center justify-between gap-2">
                          <strong>提案 {proposalVersion(draft)}</strong>
                          <Pill status={draft.status} />
                        </span>
                        <span className="mt-2 block truncate text-sm text-maker-muted">
                          {draft.payload.title || draft.payload.caption || "尚無提案內容"}
                        </span>
                        <span className="mt-2 block text-sm font-semibold text-maker-blue">點擊查看與修改 →</span>
                      </button>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="py-12 text-center text-maker-muted">尚未建立內容提案。</p>
              )}
            </div>
            </div>
          </>
        ) : (
          <p className="mt-8 rounded-xl bg-stone-50 p-6 text-center text-maker-muted">
            尚無可用 Strategy，請先完成 Agent 策略工作後再重新整理。
          </p>
        )}
      </section>
      <section className="mt-5 rounded-2xl border border-orange-200 bg-orange-50 p-6 shadow-panel" aria-labelledby="schedule-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="m-0 font-mono text-xs font-semibold tracking-[.12em] text-orange-800">SCHEDULE</p>
            <h2 id="schedule-heading" className="mt-1 text-xl">已加入排程</h2>
            <p className="mb-0 text-sm text-maker-muted">所有 Strategy 的已排程內容會集中顯示在這裡。</p>
          </div>
          <span className="rounded-full bg-white px-3 py-1 text-sm font-semibold text-orange-800">
            {scheduledDrafts.length} 則
          </span>
        </div>
        {scheduledDrafts.length ? (
          <ul className="mt-4 grid list-none gap-3 p-0 md:grid-cols-2">
            {scheduledDrafts.map((draft) => (
              <li key={draft.id} className="rounded-xl border border-orange-200 bg-white p-4">
                <strong className="block">{draft.payload.title || `提案 ${proposalVersion(draft)}`}</strong>
                <p className="mb-0 mt-2 text-sm text-maker-muted">
                  預計發布：{draft.payload.scheduled_at ? new Date(draft.payload.scheduled_at).toLocaleString("zh-TW") : "未設定時間"}
                </p>
                <button
                  type="button"
                  onClick={() => openScheduledDraft(draft)}
                  className="mt-4 rounded-lg bg-orange-700 px-3 py-2 text-sm font-semibold text-white transition hover:bg-orange-800"
                >
                  查看提案
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mb-0 mt-4 rounded-xl border border-dashed border-orange-200 bg-white/70 p-5 text-center text-sm text-maker-muted">
            尚未有內容加入排程。
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
