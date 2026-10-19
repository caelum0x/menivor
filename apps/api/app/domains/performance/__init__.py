"""Automatic performance tracking: read each posted reel's numbers on a schedule.

* :mod:`.links` - turn a pasted post link into (platform, post id).
* :mod:`.fetchers` - read one post's numbers (connected account first, then
  public endpoints) without ever inventing a number.
* :mod:`.access` - which connected platforms can share numbers, and what to
  reconnect when a permission is missing.
* :mod:`.tracker` - discovery, the scheduled refresh, pasted links, typed numbers.
* :mod:`.summary` - the results page payload (winners, chart, posts).
"""
