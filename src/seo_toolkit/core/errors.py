"""The base error for problems a user can fix: a missing key, a bad setting, an API refusal.

The dashboard and the CLI show these as plain messages instead of tracebacks.
"""


class ToolkitError(Exception):
    """Something the user can fix. The message says how."""
