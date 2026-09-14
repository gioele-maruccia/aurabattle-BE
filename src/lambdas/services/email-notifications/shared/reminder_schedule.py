"""
Exponential reminder schedule utilities.

Email reminders follow a decaying cadence from an anchor date
(account creation for basic users, profile_type_changed_at for
worker / company users):

    Send #   Days-since-anchor
    ──────   ─────────────────
       1           1
       2           3
       3           7
       4          14
       5          30
       6          60
       7          90
                 (stop)

Each user profile stores a ``email_reminders`` map in DynamoDB:

    {
      "upgrade": {"count": 2, "last_sent": "2026-01-17"},
      "worker":  {"count": 0},
      "company": {"count": 1, "last_sent": "2026-02-05"}
    }

``count`` = number of emails already sent for that reminder type.
``last_sent`` = ISO date string, for audit/debugging (optional at read time).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

# Days from anchor date when each successive email should be sent.
REMINDER_DAYS: list[int] = [1, 3, 7, 14, 30, 60, 90]

# Maximum emails per user per reminder type (len(REMINDER_DAYS)).
MAX_REMINDERS: int = len(REMINDER_DAYS)


def _parse_date(iso_str: str) -> date:
    """Parse an ISO-8601 datetime or date string to a ``date`` object."""
    # Strip trailing Z and timezone offset for simplicity; we work in UTC dates.
    iso_str = iso_str.replace("Z", "").split("+")[0].split("T")[0]
    return datetime.strptime(iso_str, "%Y-%m-%d").date()


def is_due(anchor_iso: str, sent_count: int, today: date | None = None) -> bool:
    """
    Return True if the next reminder for this user is due today or overdue.

    Args:
        anchor_iso:  ISO-8601 string for the anchor date (created_at or
                     profile_type_changed_at).
        sent_count:  How many reminders have already been sent.
        today:       Override today's date (useful for tests).
    """
    if sent_count >= MAX_REMINDERS:
        return False
    if today is None:
        today = date.today()
    try:
        anchor = _parse_date(anchor_iso)
    except (ValueError, AttributeError):
        logger.warning(f"Cannot parse anchor date '{anchor_iso}', skipping user.")
        return False
    due = anchor + timedelta(days=REMINDER_DAYS[sent_count])
    return today >= due


def reminder_data(user_item: dict, reminder_type: str) -> tuple[int, str | None]:
    """
    Extract (sent_count, last_sent) from a DynamoDB user item.

    Returns (0, None) when the key is absent (first-time user).
    """
    reminders: dict = user_item.get("email_reminders") or {}
    entry: dict = reminders.get(reminder_type) or {}
    count = int(entry.get("count", 0))
    last_sent = entry.get("last_sent")
    return count, last_sent


def build_update_expression(reminder_type: str, new_count: int, current_reminders: dict | None = None) -> dict:
    """
    Build the DynamoDB UpdateItem kwargs to update the reminder counter.

    Writes the entire ``email_reminders`` map to avoid DynamoDB ValidationException
    when the parent map attribute does not yet exist on the item.

    Example return value::
        {
          "UpdateExpression": "SET email_reminders = :val",
          "ExpressionAttributeValues": {":val": {"upgrade": {"count": 3, "last_sent": "2026-04-01"}}},
        }
    """
    today_str = date.today().isoformat()
    updated = dict(current_reminders or {})
    updated[reminder_type] = {"count": new_count, "last_sent": today_str}
    return {
        "UpdateExpression": "SET email_reminders = :val",
        "ExpressionAttributeValues": {":val": updated},
    }
