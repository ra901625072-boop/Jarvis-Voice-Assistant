# Gemini 2.5 Flash pricing (update as pricing changes)
COST_PER_1K_INPUT = 0.000075   # $0.075 / 1M input tokens
COST_PER_1K_OUTPUT = 0.0003    # $0.30 / 1M output tokens

def estimate_cost(input_tokens: int, output_tokens: int, model: str = "gemini-2.5-flash") -> float:
    return (input_tokens / 1000 * COST_PER_1K_INPUT) + (output_tokens / 1000 * COST_PER_1K_OUTPUT)
