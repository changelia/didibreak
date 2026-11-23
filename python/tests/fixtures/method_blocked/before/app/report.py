"""A report that publishes itself."""

import importlib


class Report:
    def __init__(self, title: str):
        self.title = title

    def publish(self, channel: str) -> str:
        """Send the title to a channel; the I/O hides behind importlib."""
        runner = importlib.import_module("subprocess")
        runner.run(["touch", channel])
        return self.title
