# Multi-Agent SRE System — Engineering Deep Dive

> A component-level walkthrough of how an alert becomes a diagnosed incident.
> Written from a full read of the source; every claim below is traceable to a file and line.

---

## 1. What the system actually does

When Prometheus Alertmanager fires a webhook, this system runs the investigation an
on-call engineer would run. It queries live Kubernetes state, Prometheus metrics, Loki
logs, and recent GitHub commits **in parallel**, reasons over the combined evidence with
a supervisor-coordinated LangGraph loop, decides whether it has enough to conclude,
and persists a readable investigation transcript that a human can audit and follow up on.

The design goal is a closed feedback loop, not a chatbot: the target workload produces
real symptoms, the edge layer exposes real evidence, the agent reasons, the backend
persists, and the dashboard lets an operator steer.

---

## 2. Layer map

| Layer | Path | Responsibility |
|---|---|---|
| Agent runtime | `sre_agent/` | LangGraph orchestration, supervisor routing, specialist agents |
| Edge MCP servers | `edge_mcp_servers/` | Expose live infrastructure as MCP tools |
| Control plane | `backend/` | Identity, RBAC, persistence, incidents, jobs, audit |
| Operator UI | `dashboard/` | Next.js incident transcripts, cluster state, audit trails |
| Target workload | `Target_Client/` | Generates the traffic and failures that make the demo real |

The dependency direction matters: the dashboard is a client of the backend, and the
backend owns persistence and identity but **not** the reasoning flow. The agent runtime
is the only component that orchestrates.

---

## 3. The agent runtime

### Graph topology

Built in `sre_agent/graph_builder.py:940-1016` as a LangGraph `StateGraph` over `AgentState`:

```
prepare ──> supervisor ──┬──> logs_agent ─────┐
                         ├──> metrics_agent ──┤
                         ├──> github_agent ───┼──> supervisor  (loop)
                         └──> runbooks_agent ─┘
                         │
                         └──> aggregate ──> END
```

Key structural points:

- **`prepare`** (`_prepare_initial_state`) normalizes the inbound alert before any
  reasoning happens.
- **`supervisor.route`** is a *conditional* edge (`add_conditional_edges`, line 994).
  It decides which specialist runs next, or whether to stop.
- **Every specialist edges back to the supervisor** (lines 1007-1010). This is what makes
  it a genuine reasoning loop rather than a fixed pipeline — the supervisor can dispatch,
  read the result, and dispatch again based on what it learned.
- **`aggregate`** (`supervisor.aggregate_responses`) is the single exit to `END`.

### Specialist agents

Factory functions in `sre_agent/agent_nodes.py:371-435`:

| Factory | Domain |
|---|---|
| `create_kubernetes_agent` | Pod/deployment state, events, restarts |
| `create_metrics_agent` | Prometheus golden signals |
| `create_logs_agent` | Loki log and trace queries |
| `create_github_agent` | Recent commits and pull requests |
| `create_runbooks_agent` | Playbook retrieval |

All extend `BaseAgentNode` (line 87). Tool access is deliberately **scoped per agent** by
`_filter_tools_for_agent` (line 43) — the logs agent cannot query Kubernetes. This is the
right call: it narrows each agent's decision space and stops the LLM reaching for an
irrelevant tool when a query returns empty.

### State contract

`sre_agent/agent_state.py` types the shared state with Pydantic rather than passing loose
dicts. The models that carry the reasoning:

- **`AlertContext`** — the inbound alert: name, severity, labels, annotations, `starts_at`.
- **`InvestigationFindings`** — per-domain findings (`infra_findings`, `code_findings`,
  `logs_findings`) plus a correlation timestamp.
- **`ReflectorAnalysis`** — the interesting one. Carries `discrepancies` between agent
  findings, a `hypothesis`, a bounded `confidence` float (`ge=0.0, le=1.0`), and
  `requires_deeper_investigation` with `recommended_agents`. This is the structure that
  lets the loop decide it isn't done yet.
- **`RemediationAction`** — proposed fixes.

Typing the state this way is what makes the supervisor's routing decisions inspectable
instead of vibes.

---

## 4. The MCP tool layer

Five servers under `edge_mcp_servers/mcp_servers/`, and they use **real clients**, not
fixtures:

| Server | Client library |
|---|---|
| `k8s_real` | `kubernetes` (`config.load_incluster_config` / `load_kube_config`) |
| `prometheus_real` | `prometheus_api_client.PrometheusConnect` |
| `github_real` | `PyGithub` |
| `loki_real` | `requests` against `/loki/api/v1/query_range` |
| `runbooks_local` | Local playbook retrieval |

### Reliability wrappers — the strongest part of the codebase

`sre_agent/mcp_tool_wrapper.py` composes three independent decorators over every tool:

- **Retry with backoff** — `wrap_tool_with_retry` (line 85), `max_attempts=3`, exponential
  base delay plus jitter (`multi_agent_langgraph.py:213`) so a rate-limited MCP server
  doesn't get a synchronized retry storm.
- **Audit logging** — `wrap_tool_with_audit` (line 257) with `log_audit_entry` (line 191),
  bound to incident and agent context via `set_audit_context`. Every tool call is
  attributable.
- **Circuit breaker** — `check_circuit_breaker` / `record_success` / `record_failure`
  (lines 310-343). A dead Prometheus stops being retried instead of stalling every
  investigation behind it.

Errors are typed (`ToolError`, `is_tool_error`, `parse_tool_error`) rather than raised as
bare exceptions, so a failed tool call becomes *evidence the agent can reason about*
("metrics unavailable") instead of crashing the graph.

That combination — typed errors, retry, audit, circuit breaking — is production thinking.
It is uncommon in student projects and is the thing worth pointing at in an interview.

---

## 5. Evidence of real operation

The code carries fingerprints of having actually been run against live infrastructure,
which is worth knowing because polished diagrams alone prove nothing:

- `agent_nodes.py:193` and `narrative.py:127` document a **fixed** bug where specialists
  queried with hardcoded labels like `service="web-service"` that didn't match the real
  alert, came back empty, and caused the supervisor to conclude "monitoring is broken."
  The fix threads the alert payload's actual label values into every specialist brief.
- `narrative.py:182` hardens the prompt: *"Do NOT invent labels, do NOT use placeholder
  names."*
- `agent_runtime.py:768` falls back to a minimal `AlertContext` stub when the full build
  fails, and logs it, rather than dying.

These are failures you only discover by running the system against a real cluster.

---

## 6. LLM provider abstraction

`sre_agent/llm_utils.py:38` — `create_llm_with_error_handling` supports **groq, ollama,
gemini, nvidia**, with per-provider constructors and actionable error messages (missing
`NVIDIA_API_KEY` tells you where to get a free one, line 135). Local Ollama for
development, hosted providers for real runs. No provider lock-in.

---

## 7. Known gaps

Documenting these honestly is more useful than pretending they don't exist:

| Gap | Detail |
|---|---|
| **Test coverage is thin** | 7 test files against 70 Python modules. The supervisor routing logic and circuit breaker have the highest bug-cost and the least coverage. |
| **Hardcoded token** | `benchmarks/bench_mttr.py:50` has a literal `CLUSTER_TOKEN`. Must move to env before any public deployment. |
| **No LICENSE** | The repository has no license file, which means default all-rights-reserved. |
| **Heavy local footprint** | A full demo needs Kubernetes, Prometheus, Loki and Postgres, which makes the system hard to evaluate quickly. |
| **Supervisor loop bounds** | Worth verifying the iteration cap under a pathological alert that keeps triggering `requires_deeper_investigation`. |

### What I would build next

1. Unit tests around `supervisor.route` decisions, with recorded findings as fixtures.
2. A single `docker-compose` that boots a minimal evaluable stack.
3. Circuit-breaker tests that assert the open state actually short-circuits.
4. Structured metrics on investigation quality — MTTR is measured in
   `benchmarks/bench_mttr.py`, but hypothesis accuracy is not.

---

## 8. Attribution

Original implementation by the CMPE Masters project team — **intimanjunath**,
**Ramasamy Ramanathan**, and **jayanth922** — across 19 commits between 2026-03-22 and
2026-05-02. Full history is preserved in this repository.

This document is my own technical analysis of that system.

> Note: `multi-devops-copilot-AI-system` is a squashed re-upload of this same codebase
> and shares no commit SHAs with it. This repository is the canonical history.
