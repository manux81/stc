# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Dispatch AST nodes to specialized visitor methods."""

__authors__ = ["Manuele Conti"]
__contact__ = "conti.manuele@gmail.com"
__copyright__ = "Copyright (C) 2021-2026 Manuele Conti"
__date__ = "2021/03/01"
__deprecated__ = False
__email__ =  "conti.manuele@gmail.com"
__license__ = "GPL-2.0-or-later"
__maintainer__ = "developer"
__status__ = "Production"
__version__ = "0.0.1"


class NodeVisitor:
    def __init__(self):
        pass

    def visit(self, node):
        #"""Call visit method for current node"""
        method = 'visit_' + node["name"]
        visitor = getattr(self, method, self.generic_visit)
        visitor(node)

    def generic_visit(self, node):
        #"""Called if no explicit visitor function exists for a node."""
        for child in node["children"]:
            if child == None:
                continue
            self.visit(child)

    def accept(self, node, callback=None):
        for child in node["children"]:
            if child == None:
                continue
            if callback != None and not callback(child["name"]):
                continue
            self.visit(child)
