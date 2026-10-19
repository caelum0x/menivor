"""Approvals feed: one queue of pending, hard-to-undo actions across Menivor.

Anything irreversible (publishing, replying, budget changes) becomes an
:class:`~.models.ApprovalItem` a human approves, rejects or edits. The same feed
is exposed to Rally over the bridge key. Tables from migration ``a7d3e9c1f2b4``.
"""
