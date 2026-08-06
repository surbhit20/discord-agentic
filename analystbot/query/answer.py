import anthropic


def format_answer(question: str, rows: list[dict], significance_note: str | None, client: anthropic.Anthropic) -> str:
    prompt = (
        f"Question: {question}\nResult rows: {rows}\n"
        + (f"Significance note: {significance_note}\n" if significance_note else "")
        + "Write one short, direct sentence answering the question with the number and the so-what. "
        "No preamble, no restating the question."
    )
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in response.content if b.type == "text").strip()
