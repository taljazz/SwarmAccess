"""NVDA finds an app module by the executable's name, here "Turtle Beach Swarm II.exe".

The code lives in the _swarmAccess package so it can be split into modules
and tested; this file only hands NVDA the AppModule class.
"""

from ._swarmAccess.swarmAppModule import AppModule  # noqa: F401
