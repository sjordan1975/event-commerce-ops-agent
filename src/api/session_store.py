"""In-memory coordinator session store for the Phase-B SSE wire-up.

Maps session_id → SessionEntry, which holds the ADK Runner and session object
needed to resume a coordinator turn (Turn 2 decisions, redraft).
"""

from dataclasses import dataclass

from google.adk.runners import Runner
from google.adk.sessions import Session


@dataclass
class SessionEntry:
    runner: Runner
    session: Session


_sessions: dict[str, SessionEntry] = {}


def store(session_id: str, runner: Runner, session: Session) -> None:
    """Register a new session entry."""
    _sessions[session_id] = SessionEntry(runner=runner, session=session)


def get(session_id: str) -> "SessionEntry | None":
    """Return the session entry for session_id, or None."""
    return _sessions.get(session_id)


def remove(session_id: str) -> None:
    """Remove a session entry (called after pipeline_complete)."""
    _sessions.pop(session_id, None)
