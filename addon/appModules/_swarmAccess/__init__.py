"""SwarmAccess: screen reader access to Turtle Beach Swarm II.

The package is split so that everything which does not need NVDA can be
tested with plain CPython:

* ``model`` turns a snapshot of Swarm II's UI Automation tree into a list of
  named settings.  Pure Python.
* ``pixels`` reads a switch or slider from a block of screen pixels.  Pure
  Python.
* ``uia`` takes the snapshot.  Needs a comtypes UI Automation client, which
  NVDA provides and ``tools/probe.py`` creates for itself.
* ``swarmAppModule`` is the NVDA side: naming, the settings list, and the
  mouse clicks that change things.

Nothing in this ``__init__`` may import NVDA, or the tests stop working.
"""
