# sentinel-sre — portfolio notes

> **⚠️ Before sharing this repo, fill in every `[FILL IN]` below and delete this line.**
> Everything in *My contributions* is verifiable from `git log`. Everything in
> *My role on the original build* is yours to state accurately — I have left it blank
> rather than guess, because a claim you cannot defend in an interview is worse than a
> smaller claim you can.

---

## What this system is

An autonomous incident-response system for Kubernetes. When Prometheus Alertmanager
fires, it investigates the way an on-call engineer would: pulls live cluster state,
metrics, logs, and recent commits **in parallel**, reasons over the combined evidence
with a supervisor-coordinated LangGraph loop, and writes an auditable investigation
transcript a human can read and follow up on.

**Stack:** Python · LangGraph · MCP · FastAPI · Postgres · Redis · Qdrant · Next.js ·
Kubernetes · Prometheus · Loki

- Architecture walkthrough → [`docs/SYSTEM-DEEPDIVE.md`](docs/SYSTEM-DEEPDIVE.md)
- How to evaluate it in 5 minutes → [`docs/EVALUATION.md`](docs/EVALUATION.md)

---

## Provenance

Original implementation by a Masters project team — **intimanjunath**,
**Ramasamy Ramanathan**, and **jayanth922** — across 19 commits between 2026-03-22 and
2026-05-02. This repository preserves that full history; the original remains at
[intimanjunath/Multi-Agent-SRE-System](https://github.com/intimanjunath/Multi-Agent-SRE-System),
tracked here as the `upstream` remote.

### My role on the original build

[FILL IN — be specific and be conservative. Name the components you actually worked on,
the problems you personally solved, and the decisions you argued for. If your commits
went up under a teammate's account because one person pushed for the team, say exactly
that; it is a normal thing that happens on student teams and it reads as honest.
If you mostly worked on one layer, say that too — depth in one layer is a better story
than vague credit for all of it.]

---

## My contributions in this repository

Verifiable with `git log --author="Rishidhar Reddy Garlapati"`. Commits are cited by subject rather than hash, since hashes change if history is ever rewritten.

### Found and fixed two routing bugs

> commit `fix: two routing defects in the supervisor's follow-up handling`

The supervisor's follow-up routing had no test coverage despite deciding which
specialist handles a question — a wrong call sends the whole investigation down the
wrong path. I wrote 21 tests over those pure decision helpers, which surfaced two real
defects:

- **The `"pr"` marker matched as a bare substring.** Any word starting with those two
  letters routed to the GitHub specialist — *"what is the problem?"*, *"can you approve
  this?"*, *"is there pressure on the cluster?"* all hijacked to `github_agent`. Fixed
  with word-boundary matching, keeping *"which PR broke it?"* working.
- **Human interrupts reversed the operator's stated priority.** Each named domain was
  inserted at the head of the queue in turn, so *"focus on logs first, then metrics"*
  produced a queue led by `metrics_agent`. Domains are now ranked by first mention.

Test suite: **11 → 32 tests, all passing.**

### Removed hardcoded credentials

> commit `fix: move benchmark credentials out of source into environment`

A live cluster token, cluster ID, and admin password sat as literals in
`benchmarks/bench_mttr.py`, and the same token appeared twice in a benchmark write-up.
Moved to environment variables, with the two secrets defaulting to empty so a
misconfigured run fails loudly instead of silently authenticating as someone else.

### Documented the architecture and made it evaluable

> commits `docs: add engineering deep dive of the agent runtime and MCP layer` and
> `docs: add a tiered evaluation guide; drop obsolete compose version keys`

Wrote a component-level deep dive traced to specific files and lines, and a four-tier
evaluation guide so a reviewer can form an opinion in five minutes instead of standing
up Kubernetes first. Also removed the obsolete `version` key from both compose files;
`docker compose config` now validates cleanly.

---

## What I would build next

1. Tests for the circuit breaker asserting the open state actually short-circuits.
2. A minimal control-plane-only compose target for faster evaluation.
3. Structured metrics on investigation *quality* — MTTR is measured, hypothesis
   accuracy is not.
4. A LICENSE file. `pyproject.toml` declares MIT but no license text is present.

---

## Honest limitations

- The full demo needs Kubernetes, Prometheus, Loki, and a GitHub token. See
  [`docs/EVALUATION.md`](docs/EVALUATION.md) for cheaper tiers.
- Tiers 3 and 4 of that guide are documented from the compose files but were not booted
  end to end during this work.
- Coverage is still thin relative to the codebase: 32 tests against ~17.6k lines.
