def format_refusal(missing: str) -> str:
    return f"I can't answer that — {missing}."


def format_clarify(message: str) -> str:
    return message


def format_caution(answer: str, reason: str) -> str:
    return f"{answer}\n\n_Take this with caution: {reason}_"


def format_cost_warning(bytes_estimate: int, threshold_bytes: int, price_per_tib_usd: float) -> str:
    gb = bytes_estimate / (1024 ** 3)
    tib = bytes_estimate / (1024 ** 4)
    estimated_cost = tib * price_per_tib_usd
    threshold_gb = threshold_bytes / (1024 ** 3)
    multiple = bytes_estimate / threshold_bytes if threshold_bytes else float("inf")
    return (
        f"That query would scan about **{gb:.2f} GB** — roughly **${estimated_cost:.4f}** at "
        f"BigQuery's on-demand rate (${price_per_tib_usd:.2f}/TiB), about **{multiple:.1f}x** "
        f"your {threshold_gb:.2f} GB warning threshold.\n"
        "_(BigQuery's first 1 TB of query processing per month is typically free, so this may "
        "cost nothing if you're within that.)_\n"
        "Reply `confirm` to run it anyway."
    )
