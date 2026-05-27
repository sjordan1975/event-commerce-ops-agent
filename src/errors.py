"""Cross-cutting exception types for capability precondition enforcement."""


class PreconditionError(Exception):
    """Raised when a capability cannot proceed due to missing or invalid input."""

    def __init__(self, capability: str, context: str, missing: dict[str, str]) -> None:
        self.capability = capability
        self.context = context
        self.missing = missing
        super().__init__(str(self))

    def __str__(self) -> str:
        lines = [f"Cannot do {self.capability} for {self.context}:"]
        for key, remediation in self.missing.items():
            lines.append(f"  - {key} ({remediation})")
        return "\n".join(lines)
