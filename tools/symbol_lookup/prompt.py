"""Model-visible instructions for Python structure lookup."""

PROMPT = """Use after `grep` or text retrieval has identified a likely Python file. This is
structure-only navigation; use `read_file` for exact text before an edit.

Returns file path, definition line ranges, and the file SHA-256 fingerprint.
Syntax errors return an error; use `read_file` and text search in that case.
"""
