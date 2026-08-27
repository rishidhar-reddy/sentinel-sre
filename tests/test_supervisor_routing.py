"""Tests for the supervisor's pure routing helpers.

These functions decide which specialist answers a follow-up question and how a
human interrupt reprioritizes the investigation queue. They carry the highest
bug cost in the runtime — a wrong decision sends the whole investigation down
the wrong path — and they are pure string logic, so they can be tested without
an LLM, a cluster, or a database.
"""

from sre_agent.supervisor import (
    _classify_human_interrupt,
    _follow_up_specialist_for_question,
    _is_casual_follow_up,
    _summarize_for_direct_follow_up,
)


# ── Specialist routing ────────────────────────────────────────────────────────

class TestFollowUpSpecialistRouting:
    def test_routes_metric_questions_to_the_metrics_agent(self):
        assert _follow_up_specialist_for_question("what does prometheus show?") == "metrics_agent"
        assert _follow_up_specialist_for_question("how bad was the latency?") == "metrics_agent"

    def test_routes_log_questions_to_the_logs_agent(self):
        assert _follow_up_specialist_for_question("any errors in the logs?") == "logs_agent"
        assert _follow_up_specialist_for_question("show me the stack trace") == "logs_agent"

    def test_routes_code_questions_to_the_github_agent(self):
        assert _follow_up_specialist_for_question("what changed recently?") == "github_agent"
        assert _follow_up_specialist_for_question("show me the PR that caused this") == "github_agent"
        assert _follow_up_specialist_for_question("was there a deploy?") == "github_agent"

    def test_routes_procedure_questions_to_the_runbooks_agent(self):
        assert _follow_up_specialist_for_question("what is the next step?") == "runbooks_agent"
        assert _follow_up_specialist_for_question("is there a runbook for this?") == "runbooks_agent"

    def test_returns_none_when_no_domain_matches(self):
        assert _follow_up_specialist_for_question("who is on call tonight?") is None

    def test_is_case_and_whitespace_insensitive(self):
        assert _follow_up_specialist_for_question("  ANY   ERRORS  IN  THE   LOGS ?  ") == "logs_agent"


class TestPrMarkerDoesNotMatchArbitraryWords:
    """The github marker list contains the two-letter token "pr". Matched as a
    bare substring it fires on any word beginning with those letters, which
    silently hijacks general questions to the GitHub specialist."""

    def test_problem_is_not_a_github_question(self):
        assert _follow_up_specialist_for_question("what is the problem?") != "github_agent"

    def test_approve_is_not_a_github_question(self):
        assert _follow_up_specialist_for_question("can you approve this?") != "github_agent"

    def test_pressure_is_not_a_github_question(self):
        assert _follow_up_specialist_for_question("is there pressure on the cluster?") != "github_agent"

    def test_process_is_not_a_github_question(self):
        assert _follow_up_specialist_for_question("what is the process here?") != "github_agent"

    def test_pr_as_a_standalone_word_still_routes_to_github(self):
        """The fix must not cost us the case the marker exists for."""
        assert _follow_up_specialist_for_question("which pr broke it?") == "github_agent"
        assert _follow_up_specialist_for_question("link the PR") == "github_agent"


# ── Human interrupt handling ──────────────────────────────────────────────────

QUEUE = ["logs_agent", "metrics_agent", "github_agent", "runbooks_agent"]


class TestClassifyHumanInterrupt:
    def test_plain_question_does_not_alter_the_queue(self):
        result = _classify_human_interrupt("how is it going?", QUEUE)
        assert result["mode"] == "direct_answer"
        assert "revised_queue" not in result

    def test_reroute_marker_produces_a_revised_plan(self):
        result = _classify_human_interrupt("focus on logs instead", QUEUE)
        assert result["mode"] == "revised_plan"
        assert result["revised_queue"][0] == "logs_agent"

    def test_revised_queue_preserves_every_agent(self):
        result = _classify_human_interrupt("focus on metrics", QUEUE)
        assert sorted(result["revised_queue"]) == sorted(QUEUE)

    def test_named_agent_is_promoted_without_duplication(self):
        result = _classify_human_interrupt("prioritize github", QUEUE)
        queue = result["revised_queue"]
        assert queue[0] == "github_agent"
        assert queue.count("github_agent") == 1


class TestInterruptPreservesMentionOrder:
    """When an operator names two domains, the one they asked for first must
    run first. Inserting each match at the head of the queue in turn reverses
    that intent."""

    def test_logs_before_metrics(self):
        result = _classify_human_interrupt("focus on logs first, then metrics", QUEUE)
        assert result["revised_queue"][:2] == ["logs_agent", "metrics_agent"]

    def test_metrics_before_logs(self):
        result = _classify_human_interrupt("focus on metrics first, then logs", QUEUE)
        assert result["revised_queue"][:2] == ["metrics_agent", "logs_agent"]


# ── Small helpers ─────────────────────────────────────────────────────────────

class TestCasualFollowUp:
    def test_recognizes_greetings_and_thanks(self):
        for phrase in ("hi", "hello", "thanks", "  Thank   You  "):
            assert _is_casual_follow_up(phrase) is True

    def test_a_real_question_is_not_casual(self):
        assert _is_casual_follow_up("what caused the outage?") is False


class TestSummarizeForDirectFollowUp:
    def test_empty_summary_is_reported_as_missing_context(self):
        assert "do not have the summary" in _summarize_for_direct_follow_up("")

    def test_headings_are_skipped_and_bullets_unwrapped(self):
        summary = "# Incident\n\n- Pod OOMKilled in checkout\n- Memory limit too low\n"
        out = _summarize_for_direct_follow_up(summary)
        assert out.startswith("Based on the completed investigation,")
        assert "#" not in out
        assert "- " not in out
        assert "Pod OOMKilled in checkout" in out
