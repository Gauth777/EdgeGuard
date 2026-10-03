import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowUpRight,
  Boxes,
  Cloud,
  Database,
  Radio,
  ShieldCheck,
  SlidersHorizontal,
  WifiOff,
  LogOut,
  ChevronRight,
  AlertTriangle,
  Plus,
  Check,
  Download,
} from "lucide-react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import "./style.css";

type ModelSignal = {
  sensor: string;
  value: number;
  normal_low: number;
  normal_high: number;
};
type Reading = {
  timestamp: number;
  values: Record<string, number | null>;
  quality: Record<string, string>;
  level: string;
  ml: {
    status: string;
    score: number | null;
    source_type?: string;
    model?: string;
    signals?: ModelSignal[];
  };
};
type Machine = {
  id: string;
  label: string;
  health: string;
  stale: boolean;
  age_seconds: number | null;
  latest: Reading | null;
  quality: Record<string, string>;
  limits: Record<string, number[]>;
  summary?: Record<
    string,
    { min: number; max: number; mean: number; count: number } | null
  >;
};
type Incident = {
  id: string;
  machine: string;
  status: string;
  severity: string;
  opened_at: number;
  version: number;
  acknowledged_at: number | null;
  reasons: {
    sensor?: string;
    value?: number;
    threshold?: number;
    detail?: string;
    source: string;
    model?: string;
    score?: number;
    source_type?: string;
    signals?: ModelSignal[];
  }[];
  notes: { at: number; text: string }[];
  timeline: { at: number; action: string }[];
  evidence: Reading[];
  pre?: Reading[];
  capture_complete: boolean;
  pre_seconds: number;
  model: string;
};
type State = {
  role: string;
  machines: Machine[];
  incidents: Incident[];
  pending: number;
  queue: {
    id: string;
    priority: number;
    attempts: number;
    due: number;
    error: string | null;
  }[];
  counters: Record<string, number>;
  connection: {
    status: string;
    last_success: number | null;
    error: string | null;
  };
  model: {
    status: string;
    machine: string | null;
    version?: string;
    source_type?: string;
    threshold?: number;
  };
  capacity_errors: number;
  limits: {
    queue: number;
    machines: number;
    incidents: number;
    readings_per_machine: number;
  };
  fault_controls: boolean;
};
const sensors: Record<string, string> = {
  temperature: "°C",
  vibration: "mm/s",
  pressure: "bar",
  current: "A",
  rpm: "RPM",
};
const clock = (n: number) => new Date(n * 1000).toLocaleTimeString();
const nice = (s: string) => s.replaceAll("_", " ");
function Badge({ value }: { value: string }) {
  return (
    <span className={"badge " + value.toLowerCase()}>
      <i />
      {nice(value)}
    </span>
  );
}
function App() {
  const [key, setKey] = useState("");
  const [input, setInput] = useState("");
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("Overview");
  const [selected, setSelected] = useState("");
  const [incidentId, setIncidentId] = useState("");
  const [history, setHistory] = useState<Reading[]>([]);
  const [sensor, setSensor] = useState("temperature");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [machineId, setMachineId] = useState("");
  const [label, setLabel] = useState("");
  const [notice, setNotice] = useState("");
  async function api(path: string, body?: unknown) {
    const r = await fetch("/api" + path, {
      headers: { "X-API-Key": key, "Content-Type": "application/json" },
      ...(body !== undefined
        ? { method: "POST", body: JSON.stringify(body) }
        : {}),
    });
    const data = await r.json();
    if (!r.ok)
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail),
      );
    return data;
  }
  async function refresh() {
    try {
      const s = await api("/state");
      setState(s);
      setSelected((v) => v || s.machines[0]?.id || "");
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    if (!key) return;
    let active = true;
    let timeout: ReturnType<typeof setTimeout>;
    async function poll() {
      await refresh();
      if (active) timeout = setTimeout(poll, 1000);
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timeout);
    };
  }, [key]);
  useEffect(() => {
    if (!key || !selected || state?.role !== "edge") return;
    let active = true;
    let timeout: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const h = await api(
          "/machines/" + encodeURIComponent(selected) + "/history",
        );
        if (active) setHistory(h);
      } catch {}
      if (active) timeout = setTimeout(poll, 1500);
    }
    setHistory([]);
    void poll();
    return () => {
      active = false;
      clearTimeout(timeout);
    };
  }, [key, selected, state?.role]);
  async function mutate(path: string, body: unknown) {
    setBusy(true);
    try {
      await api(path, body);
      setNotice("Saved successfully");
      await refresh();
      return true;
    } catch (e) {
      setError(String(e));
      return false;
    } finally {
      setBusy(false);
    }
  }
  const machine = state?.machines.find((m) => m.id === selected);
  const incident = state?.incidents.find((i) => i.id === incidentId);
  const active =
    state?.incidents.filter(
      (i) => !["CLOSED", "RECOVERED"].includes(i.status),
    ) || [];
  const local = state?.role === "edge";
  const chartData = history.map((r) => ({
    time: clock(r.timestamp),
    value: r.quality[sensor] === "VALID" ? r.values[sensor] : null,
  }));
  if (!key || !state)
    return (
      <div className="login">
        <div className="login-art">
          <div className="mark">
            <ShieldCheck size={28} />
          </div>
          <div className="eyebrow">INTELLIGENCE AT THE EDGE</div>
          <h1>
            Keep the signal.
            <br />
            Even when the
            <br />
            <em>connection breaks.</em>
          </h1>
          <p>
            Local monitoring. Persistent evidence.
            <br />A clear path from incident to recovery.
          </p>
          <div className="network-art">
            <Radio />
            <span />
            <Database />
            <span />
            <Cloud />
          </div>
        </div>
        <form
          className="login-form"
          onSubmit={(e) => {
            e.preventDefault();
            setKey(input);
          }}
        >
          <div className="eyebrow">EDGEGUARD / OPERATOR ACCESS</div>
          <h2>
            Your operations,
            <br />
            in focus.
          </h2>
          <p>
            Enter the access key configured for this node. Your key stays in
            this tab’s memory.
          </p>
          <label>
            Node access key
            <input
              autoFocus
              type="password"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              minLength={24}
              required
              placeholder="Enter your node key"
            />
          </label>
          <button className="primary">
            Open console <ArrowUpRight size={17} />
          </button>
          {error && <p className="error">{error}</p>}
          <small>
            Connect to the local edge node or the cloud node using its own
            address.
          </small>
        </form>
      </div>
    );
  return (
    <div className="shell">
      <aside>
        <a className="brand" href="#" onClick={(e) => e.preventDefault()}>
          <ShieldCheck />
          <strong>
            edgeguard<span>OPERATIONS CONSOLE</span>
          </strong>
        </a>
        <div className="node-label">
          <span className="green-dot" />
          {local ? "LOCAL EDGE NODE" : "CLOUD MONITOR"}
          <small>
            {local ? "On-device intelligence" : "Received data only"}
          </small>
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {[
            ["Overview", Boxes],
            ["Machine", Activity],
            ["Incidents", AlertTriangle],
            ["Delivery", Cloud],
          ].map(([name, Icon]) => (
            <button
              key={String(name)}
              className={tab === name ? "active" : ""}
              onClick={() => {
                setTab(String(name));
                setNotice("");
              }}
            >
              <Icon size={18} />
              {String(name)}
              {name === "Incidents" && active.length > 0 && (
                <b>{active.length}</b>
              )}
            </button>
          ))}
        </nav>
        <div className="aside-bottom">
          <div className="edge-card">
            <Radio size={20} />
            <strong>
              {local ? "Monitoring stays here." : "Visibility across the link."}
            </strong>
            <p>
              {local
                ? "Cloud interruptions do not stop local processing."
                : "Stale readings are labelled. Incident delivery may precede telemetry."}
            </p>
          </div>
          <button
            className="logout"
            onClick={() => {
              setKey("");
              setState(null);
              setInput("");
            }}
          >
            <LogOut size={16} /> Lock console
          </button>
          <small>EDGEGUARD · PILOT v0.1</small>
        </div>
      </aside>
      <main>
        <header>
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} />
            <strong>{tab}</strong>
          </div>
          <div className="connection">
            <span className={error ? "red-dot" : "green-dot"} />
            {error
              ? "NODE UNREACHABLE"
              : local
                ? "LOCAL NODE REACHABLE"
                : "CLOUD NODE REACHABLE"}
            <span className="divider" />
            <Cloud size={15} />
            {state.connection.status}
          </div>
        </header>
        <section className="content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {local
                  ? "LOCAL-FIRST INDUSTRIAL MONITORING"
                  : "REMOTE INDUSTRIAL MONITORING"}
              </div>
              <h1>
                {tab === "Overview"
                  ? "Operations overview"
                  : tab === "Machine"
                    ? "Machine intelligence"
                    : tab === "Incidents"
                      ? "Incident workspace"
                      : "Delivery & recovery"}
              </h1>
              <p>
                {tab === "Overview"
                  ? "Equipment health, signal quality and incident evidence in one place."
                  : tab === "Machine"
                    ? "Inspect the measurements behind every decision."
                    : tab === "Incidents"
                      ? "Follow the evidence from detection through recovery."
                      : "Know what is waiting, what was retried and what reached the cloud."}
              </p>
            </div>
            {local && tab === "Overview" && (
              <button className="primary" onClick={() => setAdding(!adding)}>
                <Plus size={16} /> Register machine
              </button>
            )}
          </div>
          {error && (
            <div role="alert" className="banner bad">
              <WifiOff size={18} />
              {error} — previously loaded values may be stale.
            </div>
          )}
          {notice && (
            <div className="banner good">
              <Check size={16} />
              {notice}
              <button onClick={() => setNotice("")}>Dismiss</button>
            </div>
          )}
          {state.capacity_errors > 0 && (
            <div className="banner bad">
              Storage capacity rejected ingestion. Restore delivery or archive
              records. Rejected requests: {state.capacity_errors}.
            </div>
          )}
          {adding && (
            <form
              className="panel registration"
              onSubmit={async (e) => {
                e.preventDefault();
                if (await mutate("/machines", { id: machineId, label })) {
                  setAdding(false);
                  setSelected(machineId);
                }
              }}
            >
              <h3>Register equipment</h3>
              <p>
                Default thresholds are illustrative motor limits. Use the API to
                supply reviewed equipment-specific limits.
              </p>
              <input
                aria-label="Machine ID"
                value={machineId}
                onChange={(e) => setMachineId(e.target.value)}
                placeholder="Machine ID · e.g. M-01"
                pattern="[A-Za-z0-9_-]{1,40}"
                required
              />
              <input
                aria-label="Machine name"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Equipment name"
                required
                maxLength={80}
              />
              <button className="primary" disabled={busy}>
                Register
              </button>
            </form>
          )}
          {tab === "Overview" && (
            <>
              <div className="metrics">
                <Metric
                  label="Registered machines"
                  value={state.machines.length}
                  detail={`${state.limits.machines} configured capacity`}
                  icon={<Boxes />}
                />
                <Metric
                  label="Active incidents"
                  value={active.length}
                  detail={
                    active.length
                      ? "Operator attention required"
                      : "No active incidents"
                  }
                  icon={<AlertTriangle />}
                />
                <Metric
                  label="Pending delivery"
                  value={state.pending}
                  detail="Durable outgoing events"
                  icon={<Cloud />}
                />
                <Metric
                  label="Sensor visibility"
                  value={`${state.machines.filter((m) => !m.stale).length}/${state.machines.length}`}
                  detail="Machines with fresh telemetry"
                  icon={<Radio />}
                />
              </div>
              <div className="overview-grid">
                <div className="panel">
                  <div className="panel-heading">
                    <h3>Equipment status</h3>
                    <span className="muted">LIVE INVENTORY</span>
                  </div>
                  {!state.machines.length ? (
                    <Empty
                      title="Connect your first machine"
                      text={
                        local
                          ? "Register equipment, then send telemetry through HTTP or MQTT."
                          : "Waiting for the edge node to send its first telemetry summary."
                      }
                    />
                  ) : (
                    <table>
                      <thead>
                        <tr>
                          <th>Equipment</th>
                          <th>Condition</th>
                          <th>Data quality</th>
                          <th>Last sample</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {state.machines.map((m) => (
                          <tr
                            key={m.id}
                            onClick={() => {
                              setSelected(m.id);
                              setTab("Machine");
                            }}
                          >
                            <td>
                              <strong>{m.label}</strong>
                              <small>{m.id}</small>
                            </td>
                            <td>
                              <Badge value={m.health} />
                            </td>
                            <td>
                              {m.stale
                                ? "STALE"
                                : Object.values(m.quality).some(
                                      (q) => q !== "VALID",
                                    )
                                  ? "DEGRADED"
                                  : "VALID"}
                            </td>
                            <td>
                              {m.age_seconds === null
                                ? "Awaiting data"
                                : `${m.age_seconds}s ago`}
                            </td>
                            <td>
                              <ChevronRight size={16} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
                <div className="panel signal-panel">
                  <div className="panel-heading">
                    <h3>Edge / cloud boundary</h3>
                    <Radio size={17} />
                  </div>
                  <div className="boundary">
                    <div>
                      <Database />
                      <strong>Local processing</strong>
                      <small>Detection · evidence · actions</small>
                    </div>
                    <div className="boundary-line">
                      {state.pending} pending events <ChevronRight size={15} />
                    </div>
                    <div>
                      <Cloud />
                      <strong>Cloud visibility</strong>
                      <small>Summaries · prioritised incidents</small>
                    </div>
                  </div>
                  <div className="subtle-note">
                    {local
                      ? "Local decisions continue when the cloud is unavailable."
                      : "This view never reads directly from the edge database."}
                  </div>
                </div>
              </div>
              <div className="panel">
                <div className="panel-heading">
                  <h3>Recent incidents</h3>
                  <button
                    className="text-button"
                    onClick={() => setTab("Incidents")}
                  >
                    View workspace <ArrowUpRight size={14} />
                  </button>
                </div>
                <IncidentList
                  incidents={state.incidents.slice(0, 5)}
                  choose={(i) => {
                    setIncidentId(i.id);
                    setTab("Incidents");
                  }}
                />
              </div>
            </>
          )}
          {tab === "Machine" && (
            <>
              <div className="toolbar">
                <select
                  aria-label="Select machine"
                  value={selected}
                  onChange={(e) => setSelected(e.target.value)}
                >
                  {state.machines.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label} / {m.id}
                    </option>
                  ))}
                </select>
                {machine && <Badge value={machine.health} />}
              </div>
              {!machine ? (
                <Empty
                  title="No machine selected"
                  text="Register a machine from Overview to start monitoring."
                />
              ) : (
                <>
                  <div className="sensor-grid">
                    {Object.entries(sensors).map(([s, unit]) => (
                      <button
                        className={
                          "panel sensor " + (sensor === s ? "selected" : "")
                        }
                        key={s}
                        onClick={() => setSensor(s)}
                      >
                        <span>{s}</span>
                        <strong>
                          {machine.stale
                            ? "—"
                            : (machine.latest?.values[s]?.toFixed(
                                s === "rpm" ? 0 : 1,
                              ) ?? "—")}{" "}
                          <small>{unit}</small>
                        </strong>
                        <Badge value={machine.quality[s] || "MISSING"} />
                      </button>
                    ))}
                  </div>
                  <div className="panel">
                    <div className="panel-heading">
                      <h3>
                        {nice(sensor)}{" "}
                        <span className="muted">/ {sensors[sensor]}</span>
                      </h3>
                      <span className="muted">
                        {local ? "LAST 120 SAMPLES" : "CLOUD SUMMARY"}
                      </span>
                    </div>
                    {local ? (
                      <div className="chart">
                        <ResponsiveContainer width="100%" height={280}>
                          <LineChart data={chartData}>
                            <CartesianGrid
                              strokeDasharray="3 5"
                              vertical={false}
                              stroke="#e4e9ee"
                            />
                            <XAxis
                              dataKey="time"
                              minTickGap={55}
                              tick={{ fontSize: 11 }}
                            />
                            <YAxis
                              domain={["auto", "auto"]}
                              tick={{ fontSize: 11 }}
                              width={48}
                            />
                            <Tooltip />
                            <Line
                              type="linear"
                              dataKey="value"
                              stroke="#167b6b"
                              strokeWidth={2}
                              dot={false}
                              connectNulls={false}
                              isAnimationActive={false}
                            />
                          </LineChart>
                        </ResponsiveContainer>
                        {!history.length && (
                          <p className="muted">
                            Waiting for readings. Invalid and missing values
                            appear as gaps.
                          </p>
                        )}
                      </div>
                    ) : (
                      <div className="summary-values">
                        {machine.summary?.[sensor] ? (
                          Object.entries(machine.summary[sensor]!).map(
                            ([k, v]) => (
                              <div key={k}>
                                <small>{k}</small>
                                <strong>{v.toFixed(2)}</strong>
                              </div>
                            ),
                          )
                        ) : (
                          <p>No summary available.</p>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="two-columns">
                    <div className="panel padded">
                      <h3>Detection configuration</h3>
                      <p>
                        Raw readings go directly to threshold checks. A rolling
                        median feeds the optional model.
                      </p>
                      <table>
                        <thead>
                          <tr>
                            <th>Sensor</th>
                            <th>Warning ≥</th>
                            <th>Critical ≥</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(machine.limits).map(([s, v]) => (
                            <tr key={s}>
                              <td>{s}</td>
                              <td>
                                {v[0]} {sensors[s]}
                              </td>
                              <td>
                                {v[1]} {sensors[s]}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="panel padded">
                      <SlidersHorizontal size={22} />
                      <h3>Statistical detection</h3>
                      <Badge
                        value={
                          machine.latest?.ml.status ||
                          (state.model.machine === machine.id
                            ? state.model.status
                            : "NOT_CALIBRATED")
                        }
                      />
                      {(machine.latest?.ml.source_type === "synthetic" ||
                        (state.model.machine === machine.id &&
                          state.model.source_type === "synthetic")) && (
                        <div className="banner bad" style={{ marginTop: 16 }}>
                          SYNTHETIC MODEL · Demonstration only. Not calibrated
                          for physical equipment.
                        </div>
                      )}
                      <p className="mono">
                        Model version:{" "}
                        {machine.latest?.ml.model ||
                          (state.model.machine === machine.id
                            ? state.model.version
                            : null) ||
                          "None"}
                      </p>
                      <p>
                        Calibrated score margin:{" "}
                        {machine.latest?.ml.score?.toFixed(4) ??
                          "Not available"}
                      </p>
                      <p>
                        A negative score margin crosses the threshold calibrated
                        on separate normal data. It is not a failure
                        probability. Missing inputs suspend model inference.
                      </p>
                      {machine.latest?.ml.signals?.length ? (
                        <>
                          <h4>Outside training reference range</h4>
                          {machine.latest.ml.signals.map((signal) => (
                            <div className="reason" key={signal.sensor}>
                              {signal.sensor}: {signal.value.toFixed(2)}
                              <small>
                                {signal.normal_low.toFixed(2)}–
                                {signal.normal_high.toFixed(2)}
                              </small>
                            </div>
                          ))}
                          <p>
                            Filtered readings versus the training 1st–99th
                            percentile range. Descriptive evidence, not causal
                            feature attribution.
                          </p>
                        </>
                      ) : null}
                      <div className="subtle-note">
                        Thresholds require equipment-specific review. The
                        interface provides monitoring, not automatic machine
                        control.
                      </div>
                    </div>
                  </div>
                </>
              )}
            </>
          )}
          {tab === "Incidents" && (
            <div className="incident-grid">
              <div className="panel">
                <div className="panel-heading">
                  <h3>Incident register</h3>
                  <span className="muted">{state.incidents.length} SHOWN</span>
                </div>
                <IncidentList
                  incidents={state.incidents}
                  choose={(i) => setIncidentId(i.id)}
                />
              </div>
              <div className="panel padded">
                {!incident ? (
                  <Empty
                    title="Select an incident"
                    text="Inspect its trigger, evidence coverage and operator history."
                  />
                ) : (
                  <>
                    <div className="incident-title">
                      <Badge value={incident.severity} />
                      <Badge value={incident.status} />
                    </div>
                    <h2>{incident.machine} / Incident</h2>
                    <p className="mono">
                      {incident.id.slice(0, 8)} · {clock(incident.opened_at)} ·
                      revision {incident.version}
                    </p>
                    <h4>Trigger evidence</h4>
                    {incident.reasons.map((r, j) => (
                      <div className="reason" key={j}>
                        {r.source === "rule"
                          ? `${r.sensor}: ${r.value} ≥ ${r.threshold} ${sensors[r.sensor!]}`
                          : r.detail}
                        <small>{r.source.toUpperCase()}</small>
                        {r.source === "model" && (
                          <p className="mono">
                            {r.source_type || "unknown source"} · {r.model} ·
                            margin {r.score?.toFixed(4)}
                          </p>
                        )}
                        {r.signals?.map((signal) => (
                          <p key={signal.sensor}>
                            {signal.sensor}: {signal.value.toFixed(2)}; training
                            reference {signal.normal_low.toFixed(2)}–
                            {signal.normal_high.toFixed(2)}
                          </p>
                        ))}
                      </div>
                    ))}
                    <div className="coverage">
                      <strong>Evidence coverage</strong>
                      <span>{incident.pre_seconds}s pre-event history</span>
                      <span>
                        {incident.capture_complete
                          ? "Post-event window captured"
                          : "Post-event window incomplete / awaiting telemetry"}
                      </span>
                      <span>
                        {
                          (incident.evidence.length
                            ? incident.evidence
                            : incident.pre || []
                          ).filter((r) =>
                            Object.values(r.quality).some((q) => q !== "VALID"),
                          ).length
                        }{" "}
                        samples with missing or invalid sensors
                      </span>
                      <small>
                        Sample timestamps in the export reveal gaps. Capture
                        does not guarantee continuous sensor coverage.
                      </small>
                    </div>
                    <button
                      className="secondary"
                      onClick={() => {
                        const url = URL.createObjectURL(
                          new Blob([JSON.stringify(incident, null, 2)], {
                            type: "application/json",
                          }),
                        );
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = `incident-${incident.id}.json`;
                        a.click();
                        URL.revokeObjectURL(url);
                      }}
                    >
                      <Download size={15} /> Export incident evidence
                    </button>
                    {local && incident.status !== "CLOSED" && (
                      <>
                        <div className="actions">
                          <button
                            disabled={busy || incident.acknowledged_at !== null}
                            className="primary"
                            onClick={() =>
                              void mutate(`/incidents/${incident.id}/actions`, {
                                action: "acknowledge",
                              })
                            }
                          >
                            Acknowledge
                          </button>
                          <button
                            disabled={busy || incident.status !== "RECOVERED"}
                            className="secondary"
                            onClick={() =>
                              void mutate(`/incidents/${incident.id}/actions`, {
                                action: "close",
                              })
                            }
                          >
                            Close recovered incident
                          </button>
                        </div>
                        <form
                          onSubmit={async (e) => {
                            e.preventDefault();
                            if (
                              await mutate(
                                `/incidents/${incident.id}/actions`,
                                { action: "note", note },
                              )
                            )
                              setNote("");
                          }}
                        >
                          <textarea
                            aria-label="Operator note"
                            value={note}
                            onChange={(e) => setNote(e.target.value)}
                            maxLength={1000}
                            required
                            placeholder="Record an inspection or maintenance observation…"
                          />
                          <button className="secondary" disabled={busy}>
                            Save note
                          </button>
                        </form>
                      </>
                    )}
                    <h4>Operator notes</h4>
                    {incident.notes.length ? (
                      incident.notes.map((n, j) => (
                        <div className="note" key={j}>
                          {n.text}
                          <small>{clock(n.at)}</small>
                        </div>
                      ))
                    ) : (
                      <p>No notes yet.</p>
                    )}
                    <h4>Incident timeline</h4>
                    <ol className="timeline">
                      {incident.timeline.map((t, j) => (
                        <li key={j}>
                          <span>{t.action}</span>
                          <time>{clock(t.at)}</time>
                        </li>
                      ))}
                    </ol>
                  </>
                )}
              </div>
            </div>
          )}
          {tab === "Delivery" && (
            <>
              <div className="metrics">
                <Metric
                  label="Pending events"
                  value={state.pending}
                  detail={`Capacity: ${state.limits.queue} events`}
                  icon={<Database />}
                />
                <Metric
                  label="Delivered events"
                  value={
                    state.counters.events_delivered ||
                    state.counters.unique_events_received ||
                    0
                  }
                  detail="Acknowledged by the cloud"
                  icon={<Check />}
                />
                <Metric
                  label="Retry failures"
                  value={state.counters.retry_failures || 0}
                  detail="Backoff capped at 30 seconds"
                  icon={<Cloud />}
                />
                <Metric
                  label="Routine events dropped"
                  value={state.counters.routine_events_dropped || 0}
                  detail="Explicit queue-pressure policy"
                  icon={<Activity />}
                />
              </div>
              <div className="two-columns">
                <div className="panel padded">
                  <h3>Transmission accounting</h3>
                  <p>
                    Payload bytes, excluding HTTP/TLS overhead. Incident
                    evidence and retries are included in attempted bytes.
                  </p>
                  {[
                    [
                      "Raw reading baseline",
                      state.counters.baseline_payload_bytes,
                    ],
                    [
                      "Attempted payload bytes",
                      state.counters.attempted_payload_bytes,
                    ],
                    [
                      "Acknowledged payload bytes",
                      state.counters.delivered_payload_bytes,
                    ],
                  ].map(([k, v]) => (
                    <div className="stat-row" key={String(k)}>
                      <span>{k}</span>
                      <strong>{Number(v || 0).toLocaleString()} B</strong>
                    </div>
                  ))}
                  <div className="subtle-note">
                    This is traffic accounting, not an assumed bandwidth savings
                    percentage. Incident-heavy operation may send more evidence.
                  </div>
                </div>
                <div className="panel padded">
                  <h3>Recovery policy</h3>
                  <p>
                    Critical notifications → incident updates → evidence →
                    routine summaries.
                  </p>
                  <p>
                    At-least-once delivery. Stable event IDs prevent duplicate
                    application; versions prevent stale updates replacing newer
                    state.
                  </p>
                  <p>
                    Last successful cloud contact:{" "}
                    {state.connection.last_success
                      ? clock(state.connection.last_success)
                      : "No contact yet"}
                  </p>
                  {state.connection.error && (
                    <div className="error">{state.connection.error}</div>
                  )}
                  {!local && state.fault_controls && (
                    <div className="actions">
                      {["offline", "lose_ack", "online"].map((mode) => (
                        <button
                          className="secondary"
                          disabled={busy}
                          key={mode}
                          onClick={() =>
                            void mutate("/testing/fault", { mode })
                          }
                        >
                          {nice(mode)}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div className="panel">
                <div className="panel-heading">
                  <h3>Outgoing queue</h3>
                  <span className="muted">FIRST 100 EVENTS</span>
                </div>
                {state.queue.length ? (
                  <table>
                    <thead>
                      <tr>
                        <th>Event</th>
                        <th>Priority</th>
                        <th>Attempts</th>
                        <th>Last error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {state.queue.map((q) => (
                        <tr key={q.id}>
                          <td className="mono">{q.id.slice(0, 12)}</td>
                          <td>
                            {
                              ["Routine", "Evidence", "Incident", "Critical"][
                                q.priority
                              ]
                            }
                          </td>
                          <td>{q.attempts}</td>
                          <td>{q.error || "Awaiting delivery"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <Empty
                    title={local ? "No events waiting" : "Cloud receipt store"}
                    text={
                      local
                        ? "New outgoing events will appear here until acknowledged."
                        : `${state.counters.duplicates_ignored || 0} duplicate deliveries ignored.`
                    }
                  />
                )}
              </div>
            </>
          )}
          <footer>
            <span>
              <ShieldCheck size={13} /> Local intelligence. Durable evidence.
            </span>
            <span>Monitoring pilot · No automatic machine actuation</span>
          </footer>
        </section>
      </main>
    </div>
  );
}
function Metric({
  label,
  value,
  detail,
  icon,
}: {
  label: string;
  value: string | number;
  detail: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="panel metric">
      <div>
        <span>{label}</span>
        {icon}
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}
function Empty({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty">
      <Radio size={28} />
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
function IncidentList({
  incidents,
  choose,
}: {
  incidents: Incident[];
  choose: (i: Incident) => void;
}) {
  return incidents.length ? (
    <div>
      {incidents.map((i) => (
        <button className="incident-row" key={i.id} onClick={() => choose(i)}>
          <div>
            <strong>{i.machine}</strong>
            <small>
              {clock(i.opened_at)} · {i.id.slice(0, 8)}
            </small>
          </div>
          <Badge value={i.severity} />
          <span className="muted">{i.status}</span>
          <ChevronRight size={16} />
        </button>
      ))}
    </div>
  ) : (
    <Empty
      title="No incidents recorded"
      text="Abnormal behaviour will create an incident with supporting evidence."
    />
  );
}
createRoot(document.getElementById("root")!).render(<App />);
