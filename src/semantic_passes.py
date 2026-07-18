# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Provide compatibility imports for the modular semantic checks.

New code should import from ``semantic_checks``.  This module remains so older
imports and tests continue to work.
"""
from semantic_checks import *  # noqa: F401,F403
