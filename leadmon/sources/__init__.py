"""Source adapters.

Each adapter is a module with three things:
  NAME             the value used in a client file: [[sources]] type = "..."
  validate(cfg)    returns a list of problems with that [[sources]] block (empty = fine)
  fetch(cfg, ctx)  returns a FetchResult with Items, errors, and an optional back-off

To add a source, write a module like reddit_rss.py and add it to ADAPTERS below.
Nothing else in the tool needs to change.
"""
from . import fixture, reddit_rss

ADAPTERS = {m.NAME: m for m in (reddit_rss, fixture)}

# Sources that reach the network and therefore need a User-Agent.
NETWORK_SOURCES = {"reddit_rss"}
