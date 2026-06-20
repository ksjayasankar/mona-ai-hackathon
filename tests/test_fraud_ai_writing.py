"""P4 AI-writing likelihood — deterministic stylometry + optional model read.
Surfaced as a WEAK, capped signal (never a reject). Tests run offline, no LLM."""
from agents import fraud as A
from agents.fraud import CVClaims

AI_TEXT = (
    "As a results-driven and detail-oriented professional, I leverage cutting-edge solutions to "
    "deliver seamless value. I am passionate about driving synergy across dynamic teams. I "
    "spearheaded innovative initiatives. I am a proven team player who thrives in fast-paced "
    "environments and consistently delivers robust, comprehensive outcomes."
)
HUMAN_TEXT = (
    "Cut p99 checkout latency from 1.8s to 240ms by sharding the orders table. Migrated 14 "
    "services off the monolith. Mentored two juniors; both were promoted. On call for the "
    "payments tier during the 2021 Black Friday peak."
)


def _c(sample, likelihood=None, reasons=None):
    return CVClaims(candidate_name="X", roles=[], skills=[], summary=None, languages=[],
                    writing_sample=sample, ai_writing_likelihood=likelihood,
                    ai_writing_reasons=reasons or [], extraction_confidence=90.0)


def test_ai_text_scores_higher_than_human():
    ai = A.ai_writing_heuristic(AI_TEXT)[0]
    human = A.ai_writing_heuristic(HUMAN_TEXT)[0]
    assert ai > human
    assert ai >= 40


def test_human_specific_text_scores_low():
    assert A.ai_writing_heuristic(HUMAN_TEXT)[0] < 30


def test_ai_writing_signal_is_weak_and_capped():
    sigs = A.ai_writing_signals(_c(AI_TEXT))
    assert sigs and all(s.weak for s in sigs)
    assert all(s.category == "writing" for s in sigs)
    # a weak signal alone must never produce HIGH
    assert A.score_risk(sigs).risk != "HIGH"


def test_short_text_not_flagged():
    assert A.ai_writing_signals(_c("Engineer.")) == []


def test_model_likelihood_blends_in():
    # heuristic-low text, but the model read says very likely -> still surfaces, still weak
    sigs = A.ai_writing_signals(_c(HUMAN_TEXT, likelihood=90, reasons=["uniform cadence"]))
    assert sigs and sigs[0].weak
    assert "%" in sigs[0].evidence


def test_no_signal_when_clean_and_model_silent():
    assert A.ai_writing_signals(_c(HUMAN_TEXT)) == []
