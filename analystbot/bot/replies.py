def format_refusal(missing: str) -> str:
    return f"I can't answer that — {missing}."


def format_clarify(message: str) -> str:
    return message


def format_caution(answer: str, reason: str) -> str:
    return f"{answer}\n\n_Take this with caution: {reason}_"


def format_cost_warning(bytes_estimate: int) -> str:
    gb = bytes_estimate / (1024 ** 3)
    return f"That query would scan about {gb:.2f} GB. Reply `confirm` to run it anyway."
