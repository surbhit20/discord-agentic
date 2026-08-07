from dataclasses import dataclass
import anthropic


@dataclass
class ConfidenceResult:
    confident: bool
    reason: str | None = None


_TOOL = {
    "name": "rate_confidence",
    "description": "Rate confidence that the given SQL correctly answers the question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "confident": {"type": "boolean"},
            "reason": {
                "type": "string",
                "description": (
                    "Required when confident is false. Hard limit: one plain-English clause, "
                    "under 15 words, no jargon, no semicolons/lists — pick the single biggest "
                    "uncertainty and drop the rest. Good: 'I guessed which event means a level "
                    "finished.' Bad: a paragraph listing every assumption about columns, types, "
                    "and table names."
                ),
            },
        },
        "required": ["confident"],
    },
}


def score_confidence(question: str, sql: str, client: anthropic.Anthropic) -> ConfidenceResult:
    prompt = (
        f"Question: {question}\nGenerated SQL: {sql}\n\n"
        "Rate whether you're confident this SQL correctly answers the question, "
        "or whether you made an uncertain assumption (e.g. about which event/param was meant). "
        "If not confident, give the reason as one short clause a non-technical teammate could "
        "read in passing — not a technical breakdown of every assumption."
    )
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=512,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "rate_confidence"},
        messages=[{"role": "user", "content": prompt}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    data = tool_use.input
    return ConfidenceResult(confident=data["confident"], reason=data.get("reason"))


_RISKY_KEYWORDS = ("JOIN", "OVER (", "PARTITION BY")


def score_risk(sql: str) -> bool:
    upper = sql.upper()
    hits = sum(1 for kw in _RISKY_KEYWORDS if kw in upper)
    return hits >= 2


def needs_caution(confidence: ConfidenceResult, risky: bool) -> bool:
    return (not confidence.confident) or risky
