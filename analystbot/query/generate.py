from dataclasses import dataclass
from enum import Enum
import json
import anthropic


class QuestionOutcome(Enum):
    MATCH = "match"
    REFUSAL = "refusal"
    CLARIFY = "clarify"


@dataclass
class QuestionResult:
    outcome: QuestionOutcome
    sql: str | None = None
    message: str | None = None
    # Set when the message also states a durable preference to remember for this user
    # ("always show me D7, not D1"). Independent of `outcome`: a message can both state
    # a preference and ask an answerable question.
    preference_to_remember: str | None = None


_TOOL = {
    "name": "answer_plan",
    "description": "Decide how to handle a game-analytics question given the discovered BigQuery schema.",
    "input_schema": {
        "type": "object",
        "properties": {
            "outcome": {"type": "string", "enum": ["match", "refusal", "clarify"]},
            "sql": {"type": "string", "description": "BigQuery SQL, required when outcome is match"},
            "message": {
                "type": "string",
                "description": "Refusal reason or clarifying question, required when outcome is refusal or clarify",
            },
            "preference_to_remember": {
                "type": "string",
                "description": (
                    "Set this ONLY when the user is explicitly asking to be remembered on future "
                    "questions (e.g. 'always show me D7, not D1', 'remember that I care about the "
                    "tutorial funnel'). Restate it as a short standalone instruction. Leave it out "
                    "for ordinary questions, one-off filters, or anything the user did not ask you "
                    "to remember. Fill it in regardless of the outcome value."
                ),
            },
        },
        "required": ["outcome"],
    },
}


def understand_and_generate(
    question: str, schema: dict, context: list[dict], preferences: list[str], client: anthropic.Anthropic
) -> QuestionResult:
    context_text = "\n".join(f"Q: {t['question']}\nSQL: {t['sql']}\nA: {t['answer']}" for t in context)
    preferences_text = "\n".join(f"- {p}" for p in preferences)
    prompt = (
        f"Discovered BigQuery schema (event_name -> param keys):\n{json.dumps(schema['events'], indent=2)}\n\n"
        f"This user's stated preferences (apply as defaults unless the question says otherwise):\n{preferences_text or '(none)'}\n\n"
        f"Prior thread/recent context:\n{context_text or '(none)'}\n\n"
        f"Question: {question}\n\n"
        "Decide: does this map to a plausible query against this schema (match), "
        "is it clearly unanswerable because the needed event/param doesn't exist (refusal), "
        "or is there no plausible mapping at all so you should ask for clarification (clarify)? "
        "Also decide whether the message states a durable preference this user wants remembered "
        "for future questions — if so, set preference_to_remember as well. "
        "Call answer_plan with your decision."
    )
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "answer_plan"},
        messages=[{"role": "user", "content": prompt}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    data = tool_use.input
    return QuestionResult(
        outcome=QuestionOutcome(data["outcome"]),
        sql=data.get("sql"),
        message=data.get("message"),
        preference_to_remember=data.get("preference_to_remember"),
    )
