import { useEffect, useState } from "react";
import { Database, Download, Pause, Play } from "lucide-react";

type Route = { id: string; representation: string; status: string; attempts: number; acknowledged: number | null; error: string | null };
type Observation = { message_id: string; machine_id: string; timestamp: number; values: Record<string, number | null>; quality: Record<string, string>; level: string; decision_version?: number; reasons?: { source: string; sensor?: string; value?: number; threshold?: number; detail?: string }[]; ml: { status: string; model?: string; score?: number | null }; routes: Route[] };
type Transfer = { id: string; machine: string; kind: string; priority: number; status: string; attempts: number; created: number; acknowledged: number | null; error: string | null; bytes: number; detail: { summary?: Record<string, { min: number; max: number; mean: number; count: number } | null>; summary_window?: {start: number; end: number; samples: number}; evidence_samples: number; version: number; entity_id: string; severity?: string } };
type Flow = { role: string; readings: Observation[]; events: Transfer[]; read_at: number; storage: { readings: number; incidents: number; queued: number; receipts: number; file_bytes: number }; counters: Record<string, number> };
const units: Record<string, string> = { temperature: "°C", vibration: "mm/s", pressure: "bar", current: "A", rpm: "RPM" };
const labels: Record<string, string> = { AGGREGATE: "Included in summary", LATEST_SNAPSHOT: "Latest reading snapshot", INCIDENT_NOTIFICATION: "Incident notification", INCIDENT_EVIDENCE: "Incident evidence" };
const time = (ts: number) => new Date(ts * 1000).toLocaleString();
const readable = (s: string) => s.replaceAll("_", " ").toLowerCase();
function Status({ value }: { value: string }) { return <span className={"flow-tag flow-" + value.toLowerCase()}>{readable(value)}</span>; }

export default function DataFlow({ accessKey, machines }: { accessKey: string; machines: {id: string; label: string}[] }) {
  const [machine, setMachine] = useState("");
  const [condition, setCondition] = useState("");
  const [paused, setPaused] = useState(false);
  const [data, setData] = useState<Flow | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (paused) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      try {
        const response = await fetch("/api/data-flow?limit=100" + (machine ? "&machine=" + encodeURIComponent(machine) : ""), { headers: {"X-API-Key": accessKey}, signal: controller.signal });
        if (!response.ok) throw new Error("Cannot read database records (HTTP " + response.status + ").");
        const result = await response.json();
        if (active) { setData(result); setError(""); }
      } catch (e) { if (active) setError(String(e)); }
      if (active) timer = setTimeout(poll, 2000);
    }
    void poll();
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [accessKey, machine, paused]);
  const local = data?.role === "edge";
  const rows = data?.readings.filter(r => !condition || (condition === "INCOMPLETE" ? Object.values(r.quality).some(q => q !== "VALID") : (r.level === "NORMAL" && Object.values(r.quality).some(q => q !== "VALID") ? "UNKNOWN" : r.level) === condition)) || [];
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/json"}));
    const a = document.createElement("a"); a.href = url; a.download = "edgeguard-data-flow.json"; a.click(); URL.revokeObjectURL(url);
  }
  return <div className="data-flow">
    <div className="flow-toolbar">
      <label>Machine<select value={machine} onChange={e => {setMachine(e.target.value); setData(null); setPaused(false);}}><option value="">All machines</option>{machines.map(m => <option key={m.id} value={m.id}>{m.id} · {m.label}</option>)}</select></label>
      {local && <label>Filter newest 100 readings<select value={condition} onChange={e => setCondition(e.target.value)}><option value="">All conditions</option><option value="NORMAL">Normal</option><option value="WARNING">Warning</option><option value="CRITICAL">Critical</option><option value="INCOMPLETE">Missing / invalid / stale</option></select></label>}
      <button onClick={() => setPaused(!paused)}>{paused ? <Play size={15}/> : <Pause size={15}/>} {paused ? "Resume updates" : "Pause to inspect"}</button>
      <button disabled={!data} onClick={download}><Download size={15}/> Export records</button>
    </div>
    {error && <div role="alert" className="flow-error">{error} Displayed records may be outdated.</div>}
    {!data ? <p role="status">Reading saved records…</p> : <>
      <div className="flow-storage"><Database size={19}/><div><strong>Read directly from {local ? "edge" : "cloud"} SQLite</strong><p>Last database read: {time(data.read_at)}{paused ? " · Updates paused" : " · Refreshes every 2 seconds"}. Records survive service restart.</p></div></div>
      <div className="flow-metrics">
        <div><span>{local ? "Raw readings retained" : "Unique cloud receipts"}</span><strong>{local ? data.storage.readings : data.storage.receipts}</strong><small>{local ? "Selected machine scope · 600 per machine cap" : "All machines · deduplicated event IDs"}</small></div>
        <div><span>{local ? "Readings processed" : "Duplicate retries ignored"}</span><strong>{data.counters[local ? "readings_processed" : "duplicates_ignored"] || 0}</strong><small>All machines · cumulative</small></div>
        <div><span>{local ? "Events awaiting acknowledgement" : "Persisted incidents"}</span><strong>{local ? data.storage.queued : data.storage.incidents}</strong><small>All machines</small></div>
        <div><span>Database + transaction log</span><strong>{(data.storage.file_bytes / 1024).toFixed(1)} KB</strong><small>Current stored file size</small></div>
      </div>
      <div className="flow-policy"><h3>How data is selected</h3><p>During a backlog, newer summaries replace unattempted pending summaries for the same machine. SUPERSEDED means earlier routine coverage was sacrificed, not delivered. Attempted/in-flight events and incident events are not replaced by this policy. Upload bodies use gzip when smaller; ledger sizes below are uncompressed logical payload sizes.</p><p>Every accepted reading is saved locally. Valid values contribute to a summary about every 15 seconds: minimum, maximum, mean and count. Critical rule breaches open incidents immediately; warnings require three consecutive readings. Compact incident notifications take priority over evidence and routine summaries. Missing or invalid values are flagged and excluded from summary statistics.</p><p><strong>A summary acknowledgement confirms delivery of the summary, not every raw reading.</strong> Local raw history retains the latest 600 readings per machine. This ledger retains 2,000 completed events plus pending events. History before this update may have no transmission record.</p></div>
      {local && <section className="flow-panel"><div className="flow-panel-heading"><h3>Saved sensor readings</h3><p>{rows.length} shown · newest 100 in the selected scope · quality and condition are recorded at ingestion</p></div>
        {!rows.length ? <p className="flow-empty">No saved readings match. Start an equipment publisher or change the filter.</p> : <div className="flow-scroll"><table><thead><tr><th>Timestamp / machine</th><th>Saved values</th><th>Sensor quality</th><th>Condition / reason</th><th>Cloud representation & delivery</th></tr></thead><tbody>{rows.map(r => <tr key={r.message_id}>
          <td><strong>{r.machine_id}</strong><br/>{time(r.timestamp)}<details><summary>Reading ID</summary><code>{r.message_id}</code></details></td>
          <td>{Object.entries(units).map(([sensor, unit]) => <div key={sensor} className="flow-value"><span>{sensor}</span><b>{r.values[sensor] == null ? "—" : Number(r.values[sensor]).toFixed(sensor === "rpm" ? 0 : 2)} {unit}</b></div>)}</td>
          <td>{Object.entries(r.quality).map(([sensor, quality]) => <div key={sensor}><span>{sensor}: </span><Status value={quality}/></div>)}</td>
          <td><Status value={r.level === "NORMAL" && Object.values(r.quality).some(q => q !== "VALID") ? "UNKNOWN" : r.level}/>
            <p>{r.reasons?.length ? r.reasons.map(reason => reason.source === "rule" ? `${reason.sensor}: ${reason.value} ≥ ${reason.threshold} (rule)` : "Unusual sensor combination (ML)").join("; ") : r.decision_version ? (Object.values(r.quality).every(q => q === "VALID") ? "No rule breach or ML anomaly detected." : "No valid rule breach; sensor data incomplete.") : "Legacy record: detailed reasons not recorded."}</p>
            <small>ML: {readable(r.ml.status)}{r.ml.model ? " · " + r.ml.model : ""}</small></td>
          <td>{r.routes.length ? <details><summary>{[...new Set(r.routes.map(x => labels[x.representation]))].join(" · ")}<div>{[...new Set(r.routes.map(x => x.status))].map(s => <Status key={s} value={s}/>)}</div></summary>{r.routes.map(route => <div className="flow-route" key={route.id + route.representation}><strong>{labels[route.representation]}</strong> <Status value={route.status}/><p>Failed attempts: {route.attempts}{route.acknowledged ? " · Acknowledged " + time(route.acknowledged) : ""}</p><code>{route.id}</code>{route.error && <p>{route.error}</p>}</div>)}</details> : <p>Saved locally · no retained cloud event for this reading. It may enter the next summary or evidence capture; older delivery history may have expired.</p>}</td>
        </tr>)}</tbody></table></div>}
      </section>}
      <section className="flow-panel"><div className="flow-panel-heading"><h3>{local ? "Transmission ledger" : "Received cloud records"}</h3><p>Newest 50 events in selected scope · {local ? "acknowledged means the edge received the cloud receipt" : "records come only from this cloud database"}</p></div>
        {!data.events.length ? <p className="flow-empty">No tracked events yet. New telemetry and incident updates will appear here.</p> : <div className="flow-scroll"><table><thead><tr><th>Created / machine</th><th>Payload</th><th>Delivery</th><th>Recorded evidence</th></tr></thead><tbody>{data.events.map(e => <tr key={e.id}><td>{e.machine}<br/>{time(e.created)}<small>{local ? "Queued locally" : "Received by cloud"}</small></td><td><strong>{e.kind === "machine" ? "Telemetry summary + latest snapshot" : "Incident update"}</strong><p>{e.bytes.toLocaleString()} bytes · priority {e.priority < 0 ? "unknown" : e.priority} · version {e.detail.version}</p></td><td><Status value={e.status}/><p>{e.attempts} failed attempts{e.acknowledged ? " · " + time(e.acknowledged) : ""}</p>{e.error && <p>{e.error}</p>}</td><td><details><summary>Inspect payload facts</summary><code>{e.id}</code>{e.detail.summary_window && <p>{e.detail.summary_window.samples} readings in window ending {time(e.detail.summary_window.end)}</p>}{e.detail.summary ? Object.entries(e.detail.summary).map(([s,v]) => <p key={s}><strong>{s}:</strong> {v ? `min ${v.min.toFixed(2)} · max ${v.max.toFixed(2)} · mean ${v.mean.toFixed(2)} · ${v.count} valid samples` : "No valid samples"}</p>) : <p>{e.detail.severity} · {e.detail.evidence_samples} raw evidence samples</p>}</details></td></tr>)}</tbody></table></div>}
      </section>
      {local ? <p className="flow-footnote">All-machine payload counters: send-every-reading baseline {data.counters.baseline_payload_bytes || 0} B · attempted uploads including retries {data.counters.attempted_payload_bytes || 0} B · acknowledged uploads {data.counters.delivered_payload_bytes || 0} B · routine events discarded under pressure {data.counters.routine_events_dropped || 0}. Payload bytes exclude HTTP overhead. Incident evidence can increase upload volume.</p> : <p className="flow-footnote">A received event is committed to cloud storage. The edge may still be retrying if its acknowledgement was lost. Raw readings remain on the edge unless included as a latest snapshot or incident evidence.</p>}
    </>}
  </div>;
}
