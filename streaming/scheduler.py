class AnalysisScheduler:
    def __init__(self, config) -> None:
        self.analysis_interval = 1.0 / max(config.analysis_fps, 0.001)
        self.court_refresh_interval = max(config.court_refresh_seconds, 0.0)
        self._last_analysis_pts = None
        self._last_court_pts = None

    def should_analyze(self, pts: float) -> bool:
        if self._last_analysis_pts is None or pts - self._last_analysis_pts >= self.analysis_interval - 1e-6:
            self._last_analysis_pts = pts
            return True
        return False

    def should_refresh_court(self, pts: float) -> bool:
        if self._last_court_pts is None or pts - self._last_court_pts >= self.court_refresh_interval - 1e-6:
            self._last_court_pts = pts
            return True
        return False
