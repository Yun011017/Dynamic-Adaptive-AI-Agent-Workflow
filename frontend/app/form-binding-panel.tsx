"use client";

import { useEffect, useState } from "react";

type Execution = { id: number; status: string };
type Source = { source_id: string; name?: string; goal_id?: number; enabled?: boolean; copy_source: string; response_count: number; execution_id: number | null };
type SourceConfig = { id: number; name: string; goal_id: number; source_id: string; timezone: string; enabled: boolean };

async function request(base: string, key: string, path: string, body?: object, method?: string) {
  const response = await fetch(`${base}${path}`, {
    method: method || (body ? "POST" : "GET"),
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const result = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(result.detail) ? result.detail.map((item) => item.msg || "資料格式不正確").join("；") : result.detail;
    throw new Error(typeof detail === "string" ? detail : result.error?.message || "表單操作失敗");
  }
  return result;
}

export default function FormBindingPanel({ strategyId, goalId, apiBase, apiKey, executionLabels }: {
  strategyId: number; goalId: number; apiBase: string; apiKey: string; executionLabels: Record<number, string>;
}) {
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [configs, setConfigs] = useState<SourceConfig[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [sourceForm, setSourceForm] = useState({ name: "", apps_script_url: "", timezone: "Asia/Taipei" });
  const [sourceBusy, setSourceBusy] = useState(false);
  const [executionId, setExecutionId] = useState("");
  const [sourceKey, setSourceKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [refresh, setRefresh] = useState(0);
  const identity = (source: Source) => JSON.stringify([source.source_id, source.copy_source]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    if (!apiKey) { setLoading(false); return; }
    Promise.all([
      request(apiBase, apiKey, `/strategies/${strategyId}/executions`),
      request(apiBase, apiKey, "/form-sources"),
      request(apiBase, apiKey, "/form-source-configs"),
    ]).then(([items, allForms, registrations]: [Execution[], Source[], SourceConfig[]]) => {
      if (cancelled) return;
      const forms = allForms.filter((form) => form.goal_id == null || form.goal_id === goalId);
      setExecutions(items);
      setSources(forms);
      setConfigs(registrations.filter((item) => item.goal_id === goalId));
      setExecutionId((current) => items.some((item) => String(item.id) === current) ? current : String(items[0]?.id || ""));
      setSourceKey((current) => forms.some((form) => identity(form) === current) ? current : "");
    }).catch((cause) => { if (!cancelled) setError(cause.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [strategyId, goalId, apiBase, apiKey, refresh]);

  const selected = sources.find((source) => identity(source) === sourceKey);
  const taken = selected?.execution_id != null && selected.execution_id !== Number(executionId);

  async function addSource(event: React.FormEvent) {
    event.preventDefault();
    setSourceBusy(true); setError(""); setMessage("");
    try {
      await request(apiBase, apiKey, "/form-source-configs", { ...sourceForm, goal_id: goalId });
      setSourceForm({ name: "", apps_script_url: "", timezone: "Asia/Taipei" });
      setShowAdd(false);
      setMessage("表單已新增，可按「同步回覆」測試讀取，再綁定執行紀錄。");
      setRefresh((value) => value + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "新增失敗"); }
    finally { setSourceBusy(false); }
  }

  async function sourceAction(source: SourceConfig, action: "sync" | "toggle") {
    setSourceBusy(true); setError(""); setMessage("");
    try {
      if (action === "sync") {
        const result = await request(apiBase, apiKey, `/form-source-configs/${source.id}/sync`, {});
        setMessage(`${source.name}：讀取 ${result.read} 筆，新增 ${result.inserted} 筆，既有 ${result.skipped} 筆。`);
      } else {
        await request(apiBase, apiKey, `/form-source-configs/${source.id}`, { enabled: !source.enabled }, "PATCH");
        setMessage(source.enabled ? "已停用同步，既有報名與綁定會保留。" : "已啟用表單來源。");
      }
      setRefresh((value) => value + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "操作失敗"); }
    finally { setSourceBusy(false); }
  }

  async function save() {
    if (!selected || !executionId) return;
    setSaving(true); setError(""); setMessage("");
    try {
      const result = await request(apiBase, apiKey, `/executions/${executionId}/form-bindings`, {
        source_id: selected.source_id, copy_source: selected.copy_source,
      });
      setMessage(`已綁定至 Execution #${result.execution_id}，補上 ${result.backfilled} 筆既有回覆；後續匯入會自動沿用。`);
      setRefresh((value) => value + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "綁定失敗"); }
    finally { setSaving(false); }
  }

  return (
    <section aria-label="報名表單綁定" className="mt-6 rounded-xl border border-maker-line bg-stone-50 p-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="m-0 text-lg">報名表單綁定</h3>
        <div className="flex gap-2">
          <button type="button" disabled={sourceBusy || !apiKey || !goalId} onClick={() => setShowAdd(!showAdd)}
            className="rounded-lg bg-maker-blue px-3 py-2 text-sm text-white disabled:opacity-50">{showAdd ? "取消新增" : "新增表單"}</button>
          <button type="button" disabled={loading || saving || sourceBusy || !apiKey} onClick={() => setRefresh((value) => value + 1)}
            className="rounded-lg bg-white px-3 py-2 text-sm disabled:opacity-50">重新整理來源</button>
        </div>
      </div>
      <p className="text-sm text-maker-muted">選擇這次宣傳使用的表單與執行紀錄，將報名歸到對應貼文。每組來源綁定後會保留，請確認人工與 AI 貼文使用各自的表單。</p>
      {showAdd && <form onSubmit={addSource} className="mb-5 space-y-3 rounded-lg border bg-white p-4">
        <h4 className="m-0 font-semibold">新增本活動的表單來源</h4>
        <label className="block text-sm">表單名稱
          <input required maxLength={255} value={sourceForm.name} disabled={sourceBusy} onChange={(event) => setSourceForm({ ...sourceForm, name: event.target.value })}
            placeholder="例如：物聯網工作坊報名" className="mt-1 w-full rounded-lg border p-2" />
        </label>
        <label className="block text-sm">Apps Script 部署網址
          <input required type="url" maxLength={2048} value={sourceForm.apps_script_url} disabled={sourceBusy} onChange={(event) => setSourceForm({ ...sourceForm, apps_script_url: event.target.value })}
            placeholder="https://script.google.com/macros/s/…/exec" className="mt-1 w-full rounded-lg border p-2" />
        </label>
        <p className="text-xs text-maker-muted">請貼上讀取回覆的部署網址，並非 Google 表單填寫連結。沿用目前人工／ai 分組或含「文案來源」欄位的表格格式。</p>
        <label className="block text-sm">回覆試算表時區
          <input required maxLength={64} value={sourceForm.timezone} disabled={sourceBusy} onChange={(event) => setSourceForm({ ...sourceForm, timezone: event.target.value })}
            className="mt-1 w-full rounded-lg border p-2" />
        </label>
        <button disabled={sourceBusy || !sourceForm.name.trim()} className="rounded-lg bg-maker-blue px-4 py-2 text-sm text-white disabled:opacity-50">{sourceBusy ? "儲存中…" : "儲存表單來源"}</button>
      </form>}
      {!!configs.length && <ul className="mb-5 list-none space-y-2 p-0">
        {configs.map((source) => <li key={source.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-white p-3">
          <span className="text-sm"><strong>{source.name}</strong> · {source.enabled ? "啟用中" : "已停用"} · {source.timezone}</span>
          <span className="flex gap-2">
            <button type="button" disabled={sourceBusy || loading || !source.enabled} onClick={() => sourceAction(source, "sync")}
              className="rounded-lg bg-stone-100 px-3 py-2 text-sm disabled:opacity-50">{sourceBusy ? "處理中…" : "同步回覆"}</button>
            <button type="button" disabled={sourceBusy || loading} onClick={() => sourceAction(source, "toggle")}
              className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50">{source.enabled ? "停用" : "啟用"}</button>
          </span>
        </li>)}
      </ul>}
      {!apiKey ? <p>請先設定連線。</p> : loading ? <p role="status">載入綁定設定中…</p> : !executions.length ?
        <p>這個策略尚無執行紀錄，請先建立內容提案。</p> : (
        <div className="grid items-end gap-4 md:grid-cols-[1fr_2fr_auto]">
          <label className="text-sm font-semibold">執行紀錄
            <select aria-label="執行紀錄" value={executionId} disabled={saving} onChange={(event) => { setExecutionId(event.target.value); setMessage(""); }} className="mt-2 w-full rounded-lg border p-2">
              {executions.map((item) => <option key={item.id} value={item.id}>Execution #{item.id} · {executionLabels[item.id] || item.status}</option>)}
            </select>
          </label>
          <label className="text-sm font-semibold">表單來源
            <select aria-label="表單來源" value={sourceKey} disabled={saving} onChange={(event) => { setSourceKey(event.target.value); setMessage(""); }} className="mt-2 w-full rounded-lg border p-2">
              <option value="">請選擇表單來源</option>
              {sources.map((source) => <option key={identity(source)} value={identity(source)} disabled={source.enabled === false}>
                {source.name || source.source_id} · {source.copy_source === "ai" ? "AI" : "人工"} · {source.response_count} 筆{source.enabled === false ? " · 已停用" : ""}{source.execution_id != null ? ` · 已綁定 #${source.execution_id}` : " · 未綁定"}
              </option>)}
            </select>
          </label>
          <button type="button" disabled={saving || sourceBusy || !selected || selected.enabled === false || !executionId || taken} onClick={save}
            className="rounded-lg bg-maker-blue px-4 py-2 font-semibold text-white disabled:opacity-50">{saving ? "儲存中…" : "儲存綁定"}</button>
        </div>
      )}
      {taken && <p className="text-sm text-amber-800">此來源已綁定 Execution #{selected?.execution_id}，請選擇其他來源。</p>}
      {!loading && !sources.length && <p className="text-sm">尚無可用來源，請先設定或同步表單。</p>}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {message && <p role="status" className="text-sm text-emerald-700">{message}</p>}
    </section>
  );
}
