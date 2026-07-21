from dataclasses import dataclass


@dataclass(frozen=True)
class AICostEstimate:
    estimated_cost_cents: float
    pricing_version: str | None
    currency: str = "USD"
    estimated: bool = False


class AICostService:
    """Single source of model pricing. Unknown models intentionally cost zero."""
    PRICING_VERSION = "2026-07"
    # cents per token: input, output. Add prices only after an explicit pricing review.
    PRICES: dict[tuple[str, str], tuple[float, float]] = {}

    def estimate(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> AICostEstimate:
        price = self.PRICES.get((provider.lower(), model.lower()))
        if price is None:
            return AICostEstimate(0, None, estimated=False)
        return AICostEstimate(input_tokens * price[0] + output_tokens * price[1], self.PRICING_VERSION, estimated=True)
