"""Small deterministic parsers for common local verification failures."""

from __future__ import annotations

import re

from services.repair.types import FailureEvidence

_LOCATION = re.compile(r"(?P<path>[A-Za-z0-9_./\\-]+\.(?:py|pyi|js|ts|tsx|jsx)):?(?P<line>\d+)?")
_PYTEST_NODE = re.compile(r"(?P<node>[^\s:]+\.py(?:::[^\s]+)+)")
_EXCEPTION = re.compile(r"(?P<exception>[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Failure|Exit))(?::\s*(?P<message>.*))?")


class FailureParser:
    def parse(self, output: str) -> tuple[FailureEvidence, ...]:
        """Extract stable evidence without assuming one test framework."""

        evidence: list[FailureEvidence] = []
        seen: set[tuple[object, ...]] = set()
        test_node_id = self._test_node_id(output)
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            location = _LOCATION.search(line)
            exception = _EXCEPTION.search(line)
            if location is None and exception is None:
                continue
            path = location.group("path").replace("\\", "/") if location else None
            number = int(location.group("line")) if location and location.group("line") else None
            exception_type = exception.group("exception") if exception else None
            message = (exception.group("message") if exception else line) or line
            item = FailureEvidence(
                category="test_failure" if test_node_id else "diagnostic",
                message=message[:1000],
                file_path=path,
                line=number,
                test_node_id=test_node_id,
                exception_type=exception_type,
            )
            key = (item.file_path, item.line, item.exception_type, item.message)
            if key not in seen:
                seen.add(key)
                evidence.append(item)
        if not evidence and output.strip():
            evidence.append(FailureEvidence(category="unparsed", message=output.strip()[:1000], test_node_id=test_node_id))
        return tuple(evidence[:12])

    @staticmethod
    def _test_node_id(output: str) -> str | None:
        matched = _PYTEST_NODE.search(output)
        return matched.group("node") if matched else None
