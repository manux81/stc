"""Compatibility facade.

New code should import from ``semantic_checks``.  This module remains so older
imports and tests continue to work.
"""
from semantic_checks import *  # noqa: F401,F403
