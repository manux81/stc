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


class CCodeGenerator(NodeVisitor):
    text = "#include <stdint.h>\n"
    indent = ""

    def __init__(self):
        pass

    def iecType2C(self, typein):
        conv = {"SINT": "int8_t" , "INT": "int16_t", "DINT": "int32_t", "LINT": "int64_t",
                "USINT": "uint8_t", "UINT": "uint16_t", "UDINT": "uint32_t", "ULINT": "uint64_t",
                "REAL" : "float", "LREAL": "double",
                "BOOL": "bool", "BYTE": "uint8_t", "WORD": "uint16_t", "DWORD": "uint32_t", "LWORD": "uint64_t",
        }
        if conv.__contains__(typein.upper()):
            return conv[typein.upper()]


    def indent_inc(self):
        self.indent += " "

    def indent_dec(self):
        self.indent = self.indent[:-1]

#########################
# B.0 Programming model #
#########################

##################
# B.1.2 Constant #
##################

############################
# B.1.2.1 Numeric literals #
############################
    def visit_integer(self, node):
        self.text += " " + node["value"] + " "

    def visit_boolean_literal(self, node):
        self.text += " " + node["value"] + " "

##############################
#  B.1.2.2 Character strings #
##############################
##########################
#  B.1.2.3 Time literals #
##########################
#######################
#  B.1.2.3.1 Duration #
#######################
###################################
#  B.1.2.3.2 Time of day and date #
###################################
#####################
#  B.1.3 Data types #
#####################
##################################
#  B.1.3.1 Elementary data types #
##################################
    def visit_signed_integer_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_unsigned_integer_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_real_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_bit_string_type_name(self, node):
        self.text += self.iecType2C(node["value"])

###############################
#  B.1.3.2 Generic data types #
###############################
##############################
# B.1.3.3 Derived data types #
##############################
###################
# B.1.4 Variables #
###################
    def visit_variable_name(self, node):
        self.text += node["value"]

##########################################
# B.1.4.1 Directly represented variables #
##########################################
###################################
# B.1.4.2 Multi-element variables #
###################################
##########################################
# B.1.4.3 Declaration and initialization #
##########################################


    def visit_var1_init_decl(self, node):
        self.accept(node, lambda name: name != 'var1_list')
        self.text += " "
        self.accept(node, lambda name: name == 'var1_list')

    def visit_var1_list(self, node):
        for child in node["children"]:
            self.visit(child)
            if child != node["children"][-1]:
                self.text += ","
####################################
# B.1.5 Program organization units #
####################################

#####################
# B.1.5.1 Functions #
#####################
    def visit_derived_function_name(self, node):
        self.text += node["value"]

    def visit_function_declaration(self, node):
        self.accept(node, lambda name: name == 'elementary_type_name')
        self.text += " "
        self.accept(node, lambda name: name == 'derived_function_name')
        self.text += "("
        self.accept(node, lambda name: name ==
                    'io_OR_function_var_declarations_list')
        self.text += ")"
        self.text += "\n{\n"
        self.indent_inc()
        self.accept(node, lambda name: name == 'function_body')
        self.indent_dec()
        self.text += "\n}"

###########################
# B.1.5.2 Function blocks #
###########################
####################
# B.1.5.3 Programs #
####################
############################################
# B.1.6 Sequential function chart elements #
############################################
################################
# B.1.7 Configuration elements #
################################
######################################
# B.2 Language IL (Instruction List) #
######################################

###################################
# B.2.1 Instructions and operands #
###################################
###################
# B.2.2 Operators #
###################
#####################################
# B.3 Language ST (Structured Text) #
#####################################

#####################
# B.3.1 Expressions #
#####################
    def visit_expression(self, node):
        for child in node["children"]:
            self.visit(child)
            if child != node["children"][-1]:
                self.text += " || "

    def visit_xor_expression(self, node):
        for child in node["children"]:
            self.visit(child)
            if child != node["children"][-1]:
                self.text += " ^ "

    def visit_and_expression(self, node):
        for child in node["children"]:
            self.visit(child)
            if child != node["children"][-1]:
                self.text += " & "

    def visit_comparison(self, node):
        for child in node["children"]:
            self.visit(child)
            if child != node["children"][-1]:
                self.text += " == "

    def visit_add_expression(self, node):
        for child in node["children"]:
            self.visit(child)

    def visit_add_operator(self, node):
        self.text += " " + node["value"] + " "

####################
# B.3.2 Statements #
####################

#################################
# B.3.2.1 Assignment statements #
#################################
    def visit_assignment_statement(self, node):
        self.text += self.indent
        self.accept(node, lambda name: name == 'variable')
        self.text += " = "
        self.accept(node, lambda name: name == 'expression')
        self.text += ";\n"



#########################################
# B.3.2.2 Subprogram control statements #
#########################################

################################
# B.3.2.3 Selection statements #
################################
    def visit_if_statement(self, node):
        self.text += self.indent + "if ("
        self.accept(node, lambda name: name == 'expression')
        self.text += ") { \n"
        self.indent_inc()
        self.accept(node, lambda name: name == 'statement_list')
        self.indent_dec()
        self.text += "\n } \n"
        self.accept(node, lambda name: name == 'elseif_statement_list')
        self.accept(node, lambda name: name == 'else_statement_list')

    def visit_elseif_statement(self, node):
        self.text += self.indent +"else if ("
        self.accept(node, lambda name: name == 'expression')
        self.text += ") { \n"
        self.indent_inc()
        self.accept(node, lambda name: name == 'statement_list')
        self.indent_dec()
        self.text += "\n" + self.indent + "} \n"

    def visit_else_statement(self, node):
        self.text += "else "
        self.text += " { \n"
        self.accept(node, lambda name: name == 'statement_list')
        self.text += " } \n"





################################
# B.3.2.4 Iteration statements #
################################
    def visit_while_statement(self, node):
        self.text += self.indent + "while ("
        self.visit(node["children"][0])
        #TODO: Replace while true with loop
        self.text += ") {\n"
        self.indent_inc()
        self.visit(node["children"][1])
        self.indent_dec()
        self.text += self.indent + "}"




