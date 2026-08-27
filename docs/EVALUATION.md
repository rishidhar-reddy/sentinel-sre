# Evaluating this system

Four tiers, cheapest first. Each one stands alone — you can stop at any level and
still have formed a real opinion. Tiers 1 and 2 are verified working on macOS
(Apple Silicon, Python 3.13, Docker Desktop). Tiers 3 and 4 are documented from the
compose files and startup scripts but have **not** been booted end to end here, so
treat their timings as estimates.

---

## Tier 0 — Read it (5 minutes, no setup)

Start with [`docs/SYSTEM-DEEPDIVE.md`](SYSTEM-DEEPDIVE.md), then the three files that
carry the design:

| File | Why |
|---|---|
| `sre_agent/graph_builder.py:940-1016` | The whole LangGraph topology in one function |
| `sre_agent/agent_state.py` | The typed state contract the agents share |
| `sre_agent/mcp_tool_wrapper.py` | Retry, audit, and circuit-breaking around every tool call |

---

## Tier 1 — Run the tests (5 minutes) ✅ verified

The fastest proof the logic is real. No database, no cluster, no API keys.

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # or: pip install pytest pytest-asyncio langgraph \
                                 #     langchain-core langchain-groq langchain-ollama \
                                 #     pydantic sqlalchemy asyncpg psycopg2-binary \
                                 #     "passlib[bcrypt]" "python-jose[cryptography]" \
                                 #     email-validator redis fastapi
pytest -q
```

Expected: **32 passed**.

Two notes if you hit trouble:

- `pytest-asyncio` is required — without it the async tests error out with
  *"async def functions are not natively supported"* rather than failing meaningfully.
  It is declared in `pyproject.toml`, so a proper `pip install -e ".[dev]"` covers it.
- Install `psycopg2-binary`, not `psycopg2`. The source package needs Postgres headers
  (`pg_config`) that most laptops do not have.

The suite covers the supervisor's routing helpers, the incident timeline CRUD layer,
and post-investigation follow-up handling.

---

## Tier 2 — Boot the control plane (15 minutes) ✅ compose validated

Brings up Postgres, Redis, Qdrant, the agent API, and the dashboard. No Kubernetes
required. The agent will not be able to *investigate* anything without the edge MCP
servers (Tier 3), but the API, auth, persistence, and UI are all exercisable.

```bash
cp .env.example .env
# set at least one LLM provider key, e.g. NVIDIA_API_KEY=...
cd platform && docker compose up -d --build
```

| Service | URL |
|---|---|
| Agent API | http://localhost:8080 |
| Dashboard | http://localhost:3002 |
| Qdrant | http://localhost:6333 |
| Redis | localhost:6380 |

The API container runs `alembic upgrade head` and `backend/seed.py` on start, so the
schema and a demo admin exist on first boot. Default seed credentials come from
`SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` (`admin@example.com` / `admin` unless
overridden). Change them before exposing anything.

LLM provider resolution order is nvidia → gemini → groq → ollama, set via
`LLM_PROVIDER`. A free NVIDIA NIM key from build.nvidia.com is the lowest-friction
option.

Tear down with `docker compose down -v`.

---

## Tier 3 — Add the edge MCP servers (~10 more minutes) ⚠️ not verified here

The five tool servers that let the agent actually gather evidence.

```bash
cd edge_mcp_servers && docker compose up -d --build
```

| Server | Host port | Needs |
|---|---|---|
| `mcp-k8s` | 4000 | A reachable kubeconfig |
| `mcp-prometheus` | 4001 | `PROMETHEUS_URL` |
| `mcp-loki` | 4002 | `LOKI_URL` |
| `mcp-github` | 4003 | `GITHUB_TOKEN`, `GITHUB_REPO` |
| `mcp-runbooks` | 4004 | nothing — local files |

The platform reaches these over `host.docker.internal`, so they are configured as host
ports rather than a shared compose network. `MCP_GITHUB_URI` is intentionally unset by
default in `platform/docker-compose.yaml` — set it once you have a token.

`docker compose config` passes cleanly on both stacks.

---

## Tier 4 — Full demo with a live target (30+ minutes) ⚠️ not verified here

Deploys the simulated microservice workload to Kubernetes so real alerts fire and the
agent investigates real symptoms.

```bash
./main_start.sh      # Target_Client → platform → edge MCP
./main_Stop.sh
```

Prerequisites beyond Tier 3: a working Kubernetes context (Docker Desktop's built-in
cluster is enough), `kubectl` on PATH, and Prometheus reachable at `localhost:9090`.
`Target_Client/start.sh` builds images and injects them into the cluster; `--no-build`
skips the rebuild on subsequent runs.

Benchmark the result with `benchmarks/bench_mttr.py` (3 runs per scenario). It reads
`SRE_BASE_URL`, `SRE_ADMIN_EMAIL`, `SRE_ADMIN_PASSWORD`, `SRE_CLUSTER_ID` and
`SRE_CLUSTER_TOKEN` from the environment.

---

## Honest cost summary

| Tier | Time | External requirements |
|---|---|---|
| 0 — read | 5 min | none |
| 1 — tests | 5 min | none |
| 2 — control plane | 15 min | Docker, one LLM key |
| 3 — evidence layer | +10 min | Prometheus, Loki, GitHub token, kubeconfig |
| 4 — full demo | 30+ min | Kubernetes cluster |

If you only have five minutes, do Tier 1. It is the only tier that proves the reasoning
logic is correct rather than merely present.
