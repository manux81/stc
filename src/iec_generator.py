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

from nodevisitor import NodeVisitor


class RustCodeGenerator(NodeVisitor):
    text = ""

    def __init__(self):
        pass

    def visit_input_declaration(self, node):
        self.accept(node)
        self.text += ";"

    def visit_function_declaration(self, node):
        self.text += "fn "
        self.accept(node, lambda name: name == 'derived_function_name')
        self.text += "("
        self.accept(node, lambda name: name ==
                    'io_OR_function_var_declarations_list')
        self.text += ") -> "
        self.accept(node, lambda name: name == 'elementary_type_name')
        self.text += "\n{\n"
        self.accept(node, lambda name: name == 'function_body')
        self.text += "\n}"

    def visit_derived_function_name(self, node):
        self.text += node["value"]

    def visit_var1_init_decl(self, node):
        self.accept(node, lambda name: name != 'var1_list')
        self.text += " "
        self.accept(node, lambda name: name == 'var1_list')

    def visit_var1_list(self, node):
        for child in node["children"]:
            self.visit(child)
            if child != node["children"][-1]:
                self.text += ","

    def visit_signed_integer_type_name(self, node):
        self.text += node["value"]

    def visit_variable_name(self, node):
        self.text += node["value"]

    def visit_assignment_statement(self, node):
        self.accept(node, lambda name: name == 'variable')
        self.text += ":="
        self.accept(node, lambda name: name == 'expression')
        self.text += ";\n"

    def visit_while_statement(self, node):
        self.text += "while "
        self.accept(node, lambda name: name == 'expression')
        self.text += " {\n"
        self.accept(node, lambda name: name == 'statement_list')
        self.text += "}"