""" Structure Text Compiler
This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
You should have received a copy of the GNU General Public License along with
this program. If not, see <http://www.gnu.org/licenses/>.
"""

__authors__ = ["Manuele Conti"]
__contact__ = "conti.manuele@gmail.com"
__copyright__ = "Copyright $YEAR, $COMPANY_NAME"
__date__ = "2021/03/01"
__deprecated__ = False
__email__ =  "conti.manuele@gmail.com"
__license__ = "GPLv3"
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

