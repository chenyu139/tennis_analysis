class DegradePolicy:
    def __init__(self, config) -> None:
        self.processing_budget_ms = max(config.processing_budget_ms, 1.0)
        self.backlog_drop_threshold = max(config.backlog_drop_threshold, 1)

    def select_quality(self, processing_ms: float, queue_size: int = 0, consecutive_failures: int = 0) -> str:
        if consecutive_failures >= 3 or queue_size >= self.backlog_drop_threshold * 2 or processing_ms >= self.processing_budget_ms * 2:
            return 'low'
        if consecutive_failures >= 1 or queue_size >= self.backlog_drop_threshold or processing_ms >= self.processing_budget_ms:
            return 'balanced'
        return 'full'
