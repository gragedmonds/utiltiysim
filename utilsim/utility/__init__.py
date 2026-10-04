"""A utility above its towns: the districts of one utility share a workforce and the networks that feed them.

* ``network``: the upstream layer (transmission circuits, the treatment plant and its transmission mains, gas gate
  stations) laid over the districts, and its events of a year, handed to each district it feeds as ``upstream``;
* ``coordinator``: one workforce allocated day by day across the districts (a home team in each, a float team sent
  where the work waits), handed to each district as its ``staffing`` schedule.
"""
