"""Domain database layer: programmatic MongoDB MCP client + wrappers.

Per D-019, the agent never calls MCP directly. McpToolset is owned here as a
programmatic client; domain wrappers (added in subsequent steps) call MongoDB
through it and are themselves exposed to the agent as FunctionTools.
"""

import json
import re

from src.db.client import MongoMCPClient

_client: MongoMCPClient | None = None


def get_client() -> MongoMCPClient:
    """Return the module-level lazy singleton MongoMCPClient."""
    global _client
    if _client is None:
        _client = MongoMCPClient()
    return _client


def _parse_docs_response(envelope: dict) -> list[dict]:
    """Parse MongoDB MCP find/aggregate envelope into a list of documents.

    MCP returns 2 content parts when results exist: part 0 is a summary string
    ("Query ... resulted in N documents"), part 1 wraps the JSON array inside
    <untrusted-user-data-UUID>...</untrusted-user-data-UUID> tags. When the
    result is empty only part 0 (the summary) is returned.

    The server's security preamble *and* footer reference those tags inline
    ("between the <open> and </close> tags"), so a single non-greedy match grabs
    the warning's "and" instead of the data block. Scan every match and return the
    first whose content parses as JSON.
    """
    for item in envelope.get("content", []):
        text = item.get("text", "")
        for match in re.finditer(
            r"<untrusted-user-data-[^>]+>(.*?)</untrusted-user-data-[^>]+>",
            text,
            re.DOTALL,
        ):
            candidate = match.group(1).strip()
            if not candidate:
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return []


__all__ = ["MongoMCPClient", "get_client", "_parse_docs_response"]
