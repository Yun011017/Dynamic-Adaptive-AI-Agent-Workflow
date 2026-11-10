"use client";

import { useEffect, useRef, useState } from "react";

const labels = {
  PENDING: "等待 worker",
  RUNNING: "執行中",
  COMPLETED: "已完成",
  FAILED: "執行失敗",
  DRAFT: "待編修",
  PENDING_REVIEW: "待審核",
  SCHEDULED: "已排程",
  SUPERSEDED: "已由新版取代",
};
const colors = {
  PENDING: "bg-amber-100 text-amber-800",
  RUNNING: "bg-blue-100 text-maker-blue",
  COMPLETED: "bg-emerald-100 text-emerald-800",
  FAILED: "bg-red-100 text-red-800",
  DRAFT: "bg-stone-100 text-stone-700",
  PENDING_REVIEW: "bg-amber-100 text-amber-800",
  SCHEDULED: "bg-orange-100 text-orange-900",
  SUPERSEDED: "bg-stone-100 text-stone-500",
};
const goalMetrics = [
  { key: "reach", label: "觸及帳號數" },
  { key: "registrations", label: "有效報名人數" },
] as const;
const blank = {
  goal: "",
  context: "",
  channel: "instagram",
  kpi: { reach: "", registrations: "" },
};
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
  external_id?: string | null;
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
    external_id?: string | null; // 若後端同時放進 payload，也可選填
  };
};
type ApprovalItem = {
  id: number;
  action_id: number;
  draft_version: number;
  content_hash: string;
  status: string;
  requested_at: string;
  action_payload?: any;
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

  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);

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
    if (!response.ok) {
      const detail = Array.isArray(body.detail)
        ? body.detail.map((item) => item.msg || "資料格式不正確").join("；")
        : body.detail;
      throw new Error(detail || body.error?.message || "後端請求失敗。");
    }
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
    return strategyValues;
  };
  const latestStrategyId = (strategyId, values = strategies) => {
    const strategy = values.find((item) => item.id === strategyId);
    if (!strategy) return strategyId;
    return values
      .filter((item) => item.goal_id === strategy.goal_id)
      .sort((a, b) => b.version - a.version || b.id - a.id)[0]?.id ?? strategyId;
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
      loadHistory().catch(() => setError("Strategy 已完成，但無法更新策略清單。"));
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
    const kpiDefinition: Record<string, number> = {};
    for (const { key, label } of goalMetrics) {
      const input = form.kpi[key].trim();
      if (!input) continue;
      const value = Number(input);
      if (!Number.isSafeInteger(value) || value < 0) {
        return setError(`${label}目標請填寫非負整數。`);
      }
      kpiDefinition[key] = value;
    }
    setError("");
    try {
      const goal = await call("/goals", {
        method: "POST",
        body: JSON.stringify({
          title: form.goal.trim(),
          description: form.context.trim() || null,
          kpi_definition: kpiDefinition,
          constraints: { channel: form.channel },
        }),
      });
      const run = await call("/agent/runs", {
        method: "POST",
        body: JSON.stringify({
          goal_id: goal.id,
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
  async function openRun(run) {
    setSelected(run.run_id);
    resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    const strategyId = await ensureStrategyForRun(run);
    if (typeof strategyId === "number") {
      // A newly completed regeneration may not be in the selector's previous
      // list yet. Refresh before setting its value so the native select can
      // render Strategy v2 instead of falling back to the first option.
      const refreshedStrategies = await loadHistory();
      setSelectedStrategy(latestStrategyId(strategyId, refreshedStrategies));
      setEditingDraft(null);
      setDraftForm(blankDraft);
    }
  }
  function strategyIdForRun(run) {
    const directId = run.output_payload?.strategy_id;
    if (typeof directId === "number") return directId;

    // Some earlier saved runs predate strategy_id in output_payload. Recover
    // their persisted Strategy through the same Goal and saved version.
    const goalId = run.goal_id
      ?? run.input_payload?.goal_id
      ?? goals.find((goal) => goal.title === run.input_payload?.goal)?.id;
    if (typeof goalId !== "number") return null;
    const version = run.output_payload?.strategy_version;
    const matches = strategies
      .filter((strategy) => strategy.goal_id === goalId)
      .sort((a, b) => b.version - a.version || b.id - a.id);
    return (typeof version === "number"
      ? matches.find((strategy) => strategy.version === version)
      : matches[0])?.id ?? null;
  }
  async function ensureStrategyForRun(run) {
    let strategyId = strategyIdForRun(run);
    try {
      if (!strategyId) {
        const savedRun = await call(`/agent/runs/${run.run_id}/strategies`, {
          method: "POST",
        });
        strategyId = savedRun.output_payload?.strategy_id;
        if (typeof strategyId !== "number") {
          throw new Error("無法建立此紀錄對應的 Strategy。");
        }
        setRuns((all) => all.map((item) =>
          item.run_id === savedRun.run_id ? savedRun : item,
        ));
        await loadHistory();
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "無法保存舊的 Strategy 紀錄。");
      return null;
    }
    return strategyId;
  }
  async function startContentProposal(run) {
    setError("");
    const strategyId = await ensureStrategyForRun(run);
    if (!strategyId) return;
    const refreshedStrategies = await loadHistory();
    setSelectedStrategy(latestStrategyId(strategyId, refreshedStrategies));
    setEditingDraft(null);
    setDraftForm(blankDraft);
    requestAnimationFrame(() => {
      document.getElementById("content-drafts")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }
  async function regenerateStrategy(run) {
    const payload = run?.input_payload;
    const goalId = run?.goal_id ?? payload?.goal_id;
    if (!goalId) return setError("這筆工作沒有可沿用的活動目標。");
    setError("");
    try {
      const nextRun = await call("/agent/runs", {
        method: "POST",
        body: JSON.stringify({
          goal_id: goalId,
          goal: payload.goal,
          context: payload.context || "",
          constraints: payload.constraints || {},
          data_source: payload.data_source || "neon_form_summary",
        }),
      });
      setRuns((all) => [nextRun, ...all]);
      setSelected(nextRun.run_id);
      setSelectedStrategy(null);
      setDrafts([]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "無法重新產生 Strategy。");
    }
  }
  async function deleteStrategyRun(run) {
    if (!window.confirm("確定刪除這筆策略工作紀錄嗎？已保存的 Strategy、內容提案與排程不會受影響。")) {
      return;
    }
    setError("");
    try {
      await call(`/agent/runs/${run.run_id}`, { method: "DELETE" });
      setRuns((all) => all.filter((item) => item.run_id !== run.run_id));
      if (selected === run.run_id) setSelected(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "無法刪除策略工作紀錄。");
    }
  }
  async function saveDraft() {
    if (!selectedStrategy) return setError("請先選擇一筆 Strategy。");
    if (!draftForm.title.trim()) return setError("請填寫提案名稱。");
    if (!draftForm.caption.trim()) return setError("請填寫貼文文案。");
    if (uniqueDraftImageUrls.length !== draftImageUrls.length) {
      return setError("圖片網址不可重複，請填寫不同的公開 HTTPS 圖片網址。");
    }
    if (draftForm.carousel && draftImageRequirements.length < 2) {
      return setError("輪播貼文至少需要兩項素材需求。");
    }
    if (draftForm.carousel && draftImageUrls.length > 0 && uniqueDraftImageUrls.length < 2) {
      return setError("輪播貼文有填圖片時，至少需要兩張不同的公開 HTTPS 圖片網址。");
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
          schedule_requested: false,
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
        setDraftForm((form) => ({ ...form, scheduleRequested: false }));
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
          schedule_requested: false,
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
  function openScheduledDraft(draft: ContentDraft) {
    const strategyId = draft.payload.strategy_id;
    if (typeof strategyId === "number") setSelectedStrategy(strategyId);
    beginRevision(draft);
  }
  const current = runs.find((run) => run.run_id === selected);
  const canStartContentProposal = current?.status === "COMPLETED";
  const strategyRuns = runs.filter(
    (run) => run.input_payload.job_type !== "CONTENT_DRAFT",
  );
  const legacyStrategyRuns = strategyRuns.filter(
    (run) => run.status === "COMPLETED" && !strategyIdForRun(run),
  );
  const selectableStrategies = Object.values(
    strategies.reduce((latest, strategy) => {
      const current = latest[strategy.goal_id];
      if (!current || strategy.version > current.version || (
        strategy.version === current.version && strategy.id > current.id
      )) {
        latest[strategy.goal_id] = strategy;
      }
      return latest;
    }, {} as Record<number, Strategy>),
  ) as Strategy[];
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
  const uniqueDraftImageUrls = [...new Set(draftImageUrls.map((url) => url.trim()))];
  const reviewRequirements = (draft: ContentDraft) => {
    const scheduledAt = draft.payload.scheduled_at;
    const validFutureTime = Boolean(scheduledAt)
      && new Date(scheduledAt as string).getTime() > Date.now();
    const imageUrls = (draft.payload.image_urls || []).map((url) => url.trim());
    const uniqueHttpsUrls = [...new Set(imageUrls.filter((url) => url.startsWith("https://")))];
    const neededImages = draft.payload.carousel ? 2 : 1;
    return [
      !validFutureTime && "未來的發布時間",
      uniqueHttpsUrls.length < neededImages
        && `至少${neededImages === 2 ? "兩張" : "一張"}公開 HTTPS 圖片網址`,
    ].filter(Boolean) as string[];
  };

  const loadApprovals = async () => {
    if (!key) return;
    try {
      const list = await call("/approval-requests?status=PENDING_REVIEW");
      setApprovals(list);
    } catch {
      setApprovals([]);
    }
  };

  useEffect(() => {
    if (key) {
      loadApprovals();
      const interval = setInterval(loadApprovals, 5000);
      return () => clearInterval(interval);
    }
  }, [key, base]);

  // 提交草稿進入審核
  const submitForReview = async (actionId: number) => {
    setError("");
    try {
      await call(`/actions/${actionId}/approval-requests`, { method: "POST" });
      await loadApprovals();
      await loadScheduledDrafts();
      if (selectedStrategy) {
        call(`/strategies/${selectedStrategy}/content-drafts`).then(setDrafts);
      }
    } catch (err: any) {
      setError(err.message || "送審失敗");
    }
  };

  // 處理人工核准 / 退回 / 拒絕
  const handleApprovalDecision = async (approvalId: number, decision: "approved" | "rejected" | "needs_revision") => {
    setError("");
    try {
      await call(`/approval-requests/${approvalId}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, reason: decision === "approved" ? "人工確認核可" : "審核未通過" }),
      });
      await loadApprovals();
      await loadScheduledDrafts();
      if (selectedStrategy) {
        call(`/strategies/${selectedStrategy}/content-drafts`).then(setDrafts);
      }
    } catch (err: any) {
      setError(err.message || "審核操作失敗");
    }
  };

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
                <fieldset className="space-y-3">
                  <legend>KPI 目標（選填）</legend>
                  <p className="text-sm">請填寫希望達到的數量，留白的項目不納入評估。</p>
                  {goalMetrics.map(({ key, label }) => (
                    <Field key={key} label={label}>
                      <input
                        className="input"
                        type="number"
                        min={0}
                        step={1}
                        value={form.kpi[key]}
                        onChange={(e) =>
                          setForm({ ...form, kpi: { ...form.kpi, [key]: e.target.value } })
                        }
                      />
                    </Field>
                  ))}
                </fieldset>
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
                <li
                  key={run.run_id}
                  className={`overflow-hidden rounded-xl border ${selected === run.run_id ? "border-[#89a9cc] bg-[#edf3f8]" : "border-maker-line"}`}
                >
                  <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-start gap-3 p-4">
                    <button
                      onClick={() => openRun(run)}
                      className="min-w-0 flex-1 text-left hover:opacity-75"
                    >
                      <strong
                        className="block truncate pr-2"
                        title={run.input_payload.goal}
                      >
                        {run.input_payload.goal}
                      </strong>
                      <small className="mt-1 block font-mono text-xs text-maker-muted">
                        {new Date(run.created_at).toLocaleString("zh-TW")}
                      </small>
                    </button>
                    <Pill status={run.status} />
                    {!['PENDING', 'RUNNING'].includes(run.status) && (
                      <button
                        type="button"
                        onClick={() => deleteStrategyRun(run)}
                        className="rounded-lg px-3 py-1 text-xs font-semibold text-red-700 transition hover:bg-red-50"
                      >
                        刪除紀錄
                      </button>
                    )}
                  </div>
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
              <div>
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <p className="m-0 text-sm text-maker-muted">
                    Strategy v{current.output_payload.strategy_version}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => startContentProposal(current)}
                      disabled={!canStartContentProposal}
                      className="rounded-lg bg-orange-700 px-3 py-2 text-sm font-semibold text-white transition hover:bg-orange-800 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {current.status === "COMPLETED"
                        ? "建立 Instagram 內容提案"
                        : "等待 Strategy 完成"}
                    </button>
                    <button
                      type="button"
                      onClick={() => regenerateStrategy(current)}
                      className="rounded-lg bg-maker-blue px-3 py-2 text-sm font-semibold text-white"
                    >
                      重新產生 Strategy
                    </button>
                  </div>
                </div>
                {!canStartContentProposal && (
                  <p className="mb-4 text-sm text-maker-muted">
                    Strategy 完成並保存後，才可以建立 Instagram 內容提案。
                  </p>
                )}
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
              value={selectedStrategy ? latestStrategyId(selectedStrategy) : ""}
              onChange={async (event) => {
                const value = event.target.value;
                if (!value) {
                  setSelectedStrategy(null);
                  return;
                }
                if (value.startsWith("legacy:")) {
                  const run = legacyStrategyRuns.find(
                    (item) => item.run_id === value.slice("legacy:".length),
                  );
                  if (!run) return;
                  setError("");
                  const strategyId = await ensureStrategyForRun(run);
                  if (strategyId) setSelectedStrategy(strategyId);
                  return;
                }
                setSelectedStrategy(latestStrategyId(Number(value)));
              }}
            >
              {!selectableStrategies.length && !legacyStrategyRuns.length && (
                <option value="">尚無可用 Strategy</option>
              )}
              {selectableStrategies.map((strategy) => (
                <option key={strategy.id} value={strategy.id}>
                  {goals.find((goal) => goal.id === strategy.goal_id)?.title || `Goal ${strategy.goal_id}`}
                </option>
              ))}
              {legacyStrategyRuns.map((run) => (
                <option key={run.run_id} value={`legacy:${run.run_id}`}>
                  {run.input_payload.goal || "未命名策略工作"} · 待保存
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
                  可先保存發布規劃；送交人工審核時必須選擇未來時間。
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
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        {draft.status === "DRAFT" && (() => {
                          const missing = reviewRequirements(draft);
                          return <>
                            <button
                              type="button"
                              disabled={missing.length > 0}
                              onClick={() => submitForReview(draft.id)}
                              className="rounded-lg bg-maker-blue px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#244e83] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              送交人工審核 →
                            </button>
                            {missing.length > 0 && (
                              <span className="text-xs text-maker-muted">
                                送交人工審核前需要完成：{missing.join("、")}
                              </span>
                            )}
                          </>;
                        })()}
                        {draft.status === "SUCCEEDED" && (
                          <span className="font-mono text-xs font-semibold text-emerald-700">
                            ✓ 已成功發布 (ID: {draft.external_id})
                          </span>
                        )}
                      </div>
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
      
      {/* ======= 加入審核專區控制台 ======= */}
      <section className="mt-5 rounded-2xl border border-amber-200 bg-amber-50/50 p-6 shadow-panel">
        <div className="flex items-center justify-between">
          <div>
            <p className="m-0 font-mono text-xs font-semibold tracking-[.12em] text-amber-800">
              HUMAN-IN-THE-LOOP APPROVAL
            </p>
            <h2 className="mt-1 text-xl">待審核貼文佇列</h2>
            <p className="mb-0 text-sm text-maker-muted">
              發布高風險操作防線：核准前絕對禁止發布，經人工審查無誤後方可放行。
            </p>
          </div>
          <span className="rounded-full bg-white px-3 py-1 text-sm font-semibold text-amber-800 shadow-sm">
            {approvals.length} 則待審
          </span>
        </div>

        {approvals.length ? (
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {approvals.map((req) => (
              <div key={req.id} className="rounded-xl border border-stone-200 bg-white p-5 shadow-sm">
                <div className="flex items-center justify-between border-b pb-2">
                  <span className="font-mono text-xs font-semibold text-stone-700">Action #{req.action_id} (v{req.draft_version})</span>
                  <span className="font-mono text-[10px] text-stone-400">HASH: {req.content_hash.slice(0, 10)}...</span>
                </div>
                <div className="mt-4 flex gap-2">
                  <button
                    type="button"
                    onClick={() => handleApprovalDecision(req.id, "approved")}
                    className="flex-1 rounded-lg bg-emerald-700 py-2 text-sm font-semibold text-white hover:bg-emerald-800"
                  >
                    核准 (Approve)
                  </button>
                  <button
                    type="button"
                    onClick={() => handleApprovalDecision(req.id, "needs_revision")}
                    className="flex-1 rounded-lg bg-amber-600 py-2 text-sm font-semibold text-white hover:bg-amber-700"
                  >
                    退回修改
                  </button>
                  <button
                    type="button"
                    onClick={() => handleApprovalDecision(req.id, "rejected")}
                    className="flex-1 rounded-lg border border-red-300 py-2 text-sm font-semibold text-red-700 hover:bg-red-50"
                  >
                    拒絕
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="mb-0 mt-4 rounded-xl border border-dashed border-stone-200 bg-white/70 p-5 text-center text-sm text-maker-muted">
            目前沒有等待審核的提案。
          </p>
        )}
      </section>
      {/* ================================= */}
      <section className="mt-5 rounded-2xl border border-orange-200 bg-orange-50 p-6 shadow-panel" aria-labelledby="schedule-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="m-0 font-mono text-xs font-semibold tracking-[.12em] text-orange-800">SCHEDULE</p>
            <h2 id="schedule-heading" className="mt-1 text-xl">已加入排程</h2>
            <p className="mb-0 text-sm text-maker-muted">人工審核完成的內容會集中顯示在這裡。</p>
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
            尚未有審核完成的內容加入排程。
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
