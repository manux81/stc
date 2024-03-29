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

# Note sly operator
#    ? for optional sly equivalent [ ... ]
#    * for 0 or more  sly equivalent { ... }
#    + for 1 or more  sly equivalent  element { element }

from yacc import Parser
from iec_lexer import IECLexer
import sys


class IECParser(Parser):
    start = 'library'
    debugfile = 'parser.out'
    tokens = IECLexer.tokens



    def __init__(self, variables: dict = None):
        self.variables = variables or {}
        self.stack = []

    @property
    def last_item_on_stack(self):
        return self.stack[-1] if len (self.stack) > 0 else None

    def method_name():
        return sys._getframe.f_code.co_name

#########################
# B.0 Programming model #
#########################
    @_('', 'library library_element_declaration')
    def library(self, p):
        if len(p) > 0:
            return { "name": self.production.name, "children": [ p[1] ] }

#    @_('data_type_name', 'function_name',
#       'function_block_type_name', 'program_type_name',
#       'resource_type_name', 'configuration_name')
#    def library_element_name(self, p):
#        pass

    @_('data_type_declaration',
       'function_declaration', 'function_block_declaration',
       'program_declaration', 'configuration_declaration')
    def library_element_declaration(self, p):
        return { "name": self.production.name, "children": [ p[0] ] }

##################
# B.1.2 Constant #
##################
    @_('numeric_literal', 'character_string', 'time_literal',
       'bit_string_literal', 'boolean_literal')
    def constant(self, p):
        return { "name": self.production.name, "children": [ p[0] ] }

############################
# B.1.2.1 Numeric literals #
############################
    @_('integer_literal', 'real_literal')
    def numeric_literal(self, p):
        return { "name": self.production.name, "children": [ p[0] ] }

    @_('[ integer_type_name "#" ] signed_integer',
       '[ integer_type_name "#" ] binary_integer',
       '[ integer_type_name "#" ] octal_integer',
       '[ integer_type_name "#" ] hex_integer') 
    def integer_literal(self, p):
        return { "name": self.production.name, "value": p[0][1], "children": [ p[1] ] }

    @_('"+" integer', '"-" integer')
    def signed_integer(self, p):
        pass

    @_('INTEGER')
    def integer(self, p):
        return { "name": self.production.name, "value": p[0], "children": [ None ] }

    @_('BINARY_INTEGER')
    def binary_integer(self, p):
        pass

    @_('OCTAL_INTEGER')
    def octal_integer(self, p):
        pass

    @_('HEX_INTEGER')
    def hex_integer(self, p):
        pass

    @_('real_type_name [ "#" ] signed_integer "." integer',
       'real_type_name [ "#" ] signed_integer "." integer exponent')
    def real_literal(self, p):
        pass

    @_('"E" [ "+" ] integer', '"E" [ "-" ] integer',
       '"e" [ "+" ] integer', '"e" [ "-" ] integer',)
    def exponent(self, p):
        pass

    @_('[ BYTE "#" ] integer', '[ BYTE "#" ] binary_integer',
       '[ BYTE "#" ] octal_integer', '[ BYTE "#" ] hex_integer',
       '[ WORD "#" ] integer', '[ WORD "#" ] binary_integer',
       '[ WORD "#" ] octal_integer', '[ WORD "#" ] hex_integer',
       '[ DWORD "#" ] integer', '[ DWORD "#" ] binary_integer',
       '[ DWORD "#" ] octal_integer', '[ DWORD "#" ] hex_integer',
       '[ LWORD "#" ] integer', '[ LWORD "#" ] binary_integer',
       '[ LWORD "#" ] octal_integer', '[ LWORD "#" ] hex_integer')
    def bit_string_literal(self, p):
        return  { "name": self.production.name, "value": p[0][0], "children": [ p[1] ] }
    # NOTE: see note under the B 1.2.1 section of token
    # and grouping type definition for reason why the use of
    # bit_string_type_name, although seemingly incorrect, is
    # really correct here!


    @_('[ BOOL "#" ] "1"', '[ BOOL "#" ] "0"', 'TRUE', 'FALSE')
    def boolean_literal(self, p):
        if len(p) == 1:
            return  { "name": self.production.name, "value": p[0], "children": [ None ] }
        return  { "name": self.production.name, "value": p[1], "children": [ None ] }

##############################
#  B.1.2.2 Character strings #
##############################
    @_('single_byte_character_string',
       'double_byte_character_string')
    def character_string(self, p):
        pass

    @_( '"\'" "\'"',
        '"\'" single_byte_character_representation "\'"')
    def single_byte_character_string(self, p):
        pass

    @_( '"\"" "\""',
        '"\"" double_byte_character_representation "\""')
    def double_byte_character_string(self, p):
        pass

    @_('common_character_representation', 'DOLLAR_APC', '"\""', '"$" HEX_DIGIT HEX_DIGIT',)
    def single_byte_character_representation(self, p):
        pass

    @_('common_character_representation', 'DOLLAR_QOT', '"\'"', '"$" HEX_DIGIT HEX_DIGIT HEX_DIGIT HEX_DIGIT')
    def double_byte_character_representation(self, p):
        pass

    @_('PRINTABLE_CHAR', 'DOLLAR_DOLLAR', 'DOLLAR_L', 'DOLLAR_N', 'DOLLAR_P')
    def common_character_representation(self, p):
        pass
#'$R' | '$T' | '$l' | '$n' | '$p' | '$r' | '$t'

##########################
#  B.1.2.3 Time literals #
##########################
    @_('duration', 'time_of_day', 'date', 'date_and_time')
    def time_literal(self, p):
        pass

#######################
#  B.1.2.3.1 Duration #
#######################
    @_('"T" "#" [ "-" ] interval',
       'TIME "#" [ "-" ] interval')
    def duration(self, p):
        pass

    @_('days',  'hours', 'minutes', 'seconds', 'milliseconds')
    def interval(self, p):
        pass

    @_('fixed_point "d"', 'integer "d" [ "_" ]  hours')
    def days(self, p):
        pass

    @_('integer [ "." integer ] ')
    def fixed_point(self, p):
        pass

    @_('fixed_point "h"', 'integer "h" [ "_" ] minutes')
    def hours(self, p):
        pass

    @_('fixed_point "m"', 'integer "m" [ "_" ] seconds')
    def minutes(self, p):
        pass

    @_('fixed_point "s"', 'integer "s" [ "_" ] milliseconds')
    def seconds(self, p):
        pass

    @_('fixed_point MS')
    def milliseconds(self, p):
        pass

###################################
#  B.1.2.3.2 Time of day and date #
###################################

    @_('TIME_OF_DAY "#" daytime', 'TOD "#" daytime')
    def time_of_day(self, p):
        pass

    @_('day_hour ":" day_minute ":" day_second')
    def daytime(self, p):
       pass

    @_('integer')
    def day_hour(self,p):
        pass
 
    @_('integer')
    def day_minute(self, p):
        pass
 
    @_('fixed_point')
    def day_second(self, p):
        pass
 
    @_('DATE "#" date_literal', '"D" "#" date_literal')
    def date(self, p):
        pass
 
    @_('year "-" month "-" day') 
    def date_literal(self, p):
        pass
 
    @_('integer')
    def year(self, p):
        pass
 
    @_('integer')
    def month(self, p):
        pass
 
    @_('integer')
    def day(self, p):
        pass
 
    @_('DATE_AND_TIME "#" date_literal "-" daytime',
       'DT "#" date_literal "-" daytime')
    def date_and_time(self, p):
        pass
 
#####################
#  B.1.3 Data types #
#####################
#   @_('non_generic_type_name', 'generic_type_name')
#   def data_type_name(self, p):
#       pass

    @_('elementary_type_name', 'derived_type_name')
    def non_generic_type_name(self, p):
        pass

##################################
#  B.1.3.1 Elementary data types #
##################################
    @_('numeric_type_name', 'date_type_name', 'bit_string_type_name', 'STRING', 
       'WSTRING', 'TIME')
    def elementary_type_name(self, p):
        return {"name": self.production.name, "children": [ p[0] ]}

    @_('integer_type_name', 'real_type_name')
    def numeric_type_name(self, p):
        return {"name": self.production.name, "children": [ p[0] ]}

    @_('signed_integer_type_name', 'unsigned_integer_type_name')
    def integer_type_name(self, p):
        return {"name": self.production.name, "children": [ p[0] ]}

    @_('SINT', 'INT', 'DINT', 'LINT')
    def signed_integer_type_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('USINT', 'UINT', 'UDINT', 'ULINT')
    def unsigned_integer_type_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('REAL', 'LREAL')
    def real_type_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('DATE', 'TIME_OF_DAY', 'TOD', 'DATE_AND_TIME', 'DT')
    def date_type_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('BOOL', 'BYTE', 'WORD', 'DWORD', 'LWORD')
    def bit_string_type_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}


###############################
#  B.1.3.2 Generic data types #
###############################
#    @_('ANY', 'ANY_DERIVED', 'ANY_ELEMENTARY',
#       'ANY_MAGNITUDE', 'ANY_NUM', 'ANY_REAL', 'ANY_INT', 'ANY_BIT',
#       'ANY_STRING', 'ANY_DATE')
#    def generic_type_name(self, p):
#        pass

##############################
# B.1.3.3 Derived data types #
##############################
    @_('single_element_type_name', 'array_type_name',
       'structure_type_name', 'string_type_name')
    def derived_type_name(self, p):
        pass

    @_('simple_type_name', 'subrange_type_name', 'enumerated_type_name')
    def single_element_type_name(self, p):
        pass

    @_('IDENTIFIER')
    def simple_type_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('IDENTIFIER')
    def subrange_type_name(self, p):
       return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('IDENTIFIER')
    def enumerated_type_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('IDENTIFIER')
    def array_type_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('IDENTIFIER') 
    def structure_type_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('TYPE type_declaration ";" { type_declaration ";" } END_TYPE')
    def data_type_declaration(self, p):
        pass

    @_('single_element_type_declaration',
       'array_type_declaration',
       'structure_type_declaration', 'string_type_declaration')
    def type_declaration(self, p):
        pass

    @_('simple_type_declaration',
      'subrange_type_declaration', 'enumerated_type_declaration')
    def single_element_type_declaration(self, p):
        pass

    @_('simple_type_name ":" simple_spec_init')
    def simple_type_declaration(self, p):
        pass

    @_('simple_specification [ ASSIGN constant ]')
    def simple_spec_init(self, p):
        if p[1][0] == None:
            return {"name": "simple_spec_init", "children": [ p[0] ]}
        return {"name": self.production.name, "children": [ p[0], p[1][1] ]}


    @_('elementary_type_name', 'simple_type_name')
    def simple_specification(self, p):
        return {"name": self.production.name, "children": [ p[0] ]}

    @_('subrange_type_name ":" subrange_spec_init')
    def subrange_type_declaration(self, p):
        pass

    @_('subrange_specification [ ASSIGN signed_integer ]')
    def subrange_spec_init(self, p):
        pass

    @_('integer_type_name "(" subrange ")"',
        'subrange_type_name')
    def subrange_specification(self, p):
        pass

    @_('signed_integer DOTDOT signed_integer')
    def subrange(self, p):
        pass

    @_('enumerated_type_name ":" enumerated_spec_init')
    def enumerated_type_declaration(self, p):
        pass

    @_('enumerated_specification [ ASSIGN enumerated_value ]')
    def enumerated_spec_init(self, p):
        pass

    @_('"(" enumerated_value { "," enumerated_value } ")"',
       'enumerated_type_name')
    def enumerated_specification(self, p):
        pass

    @_('[ enumerated_type_name "#" ] IDENTIFIER')
    def enumerated_value(self, p):
        pass

    @_('array_type_name ":" array_spec_init')
    def array_type_declaration(self, p):
        pass

    @_('array_specification [ ASSIGN array_initialization ]')
    def array_spec_init(self, p):
        pass

    @_('array_type_name',
       'ARRAY "[" subrange { "," subrange } "]" OF non_generic_type_name')
    def array_specification(self, p):
        pass

    @_('"[" array_initial_elements { "," array_initial_elements } "]"')
    def array_initialization(self, p):
        pass

    @_('array_initial_element', 'integer "(" [ array_initial_element ] ")"')
    def array_initial_elements(self, p):
        pass

    @_('constant', 'enumerated_value', 'structure_initialization', 'array_initialization')
    def array_initial_element(self, p):
        pass

    @_('structure_type_name ":" structure_specification')
    def structure_type_declaration(self, p):
        pass

    @_('structure_declaration', 'initialized_structure')
    def structure_specification(self, p):
        pass


    @_('structure_type_name [ ASSIGN structure_initialization ]')
    def initialized_structure(self, p):
        pass

    @_('STRUCT structure_element_declaration ";" { structure_element_declaration ";" } END_STRUCT')
    def structure_declaration(self, p):
        pass

    @_('structure_element_name ":" simple_spec_init', 
       'structure_element_name ":" subrange_spec_init',
       'structure_element_name ":" enumerated_spec_init',
       'structure_element_name ":" array_spec_init',
       'structure_element_name ":" initialized_structure')
    def structure_element_declaration(self, p):
        pass

    @_('IDENTIFIER')
    def structure_element_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('"(" structure_element_initialization "," { "," structure_element_initialization } ")"')
    def structure_initialization(self, p):
        pass

    @_('structure_element_name ASSIGN constant',
       'structure_element_name ASSIGN enumerated_value',
       'structure_element_name ASSIGN array_initialization',
       'structure_element_name ASSIGN structure_initialization')
    def structure_element_initialization(self, p):
        pass

    @_('IDENTIFIER')
    def string_type_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('string_type_name ":" STRING [ "[" integer "]" ] [ ASSIGN character_string ]',
       'string_type_name ":" WSTRING [ "[" integer "]" ] [ ASSIGN character_string ]')
    def string_type_declaration(self, p):
        pass

###################
# B.1.4 Variables #
###################
    @_('direct_variable', 'symbolic_variable')
    def variable(self, p):
        return {"name": self.production.name, "children": [ p[0] ]}

    @_('variable_name', 'multi_element_variable')
    def symbolic_variable(self, p):
        return {"name": self.production.name, "children": [ p[0] ]}

    @_('IDENTIFIER')
    def variable_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}



##########################################
# B.1.4.1 Directly represented variables #
##########################################
    @_('"%" location_prefix size_prefix integer { "." integer }')
    def direct_variable(self, p):
        pass

    @_('"I"','"Q"','"M"')
    def location_prefix(self, p):
        pass

    @_('NIL', '"X"', '"B"', '"W"', '"D"', '"L"')
    def size_prefix(self, p):
        pass

###################################
# B.1.4.2 Multi-element variables #
###################################
    @_('array_variable', 'structured_variable')
    def multi_element_variable(self, p):
        pass

    @_('subscripted_variable subscript_list')
    def array_variable(self, p):
        pass

    @_('symbolic_variable')
    def subscripted_variable(self, p):
        pass

    @_('"[" subscript { "," subscript } "]"')
    def subscript_list(self, p):
        pass

    @_('expression')
    def subscript(self, p):
        pass

    @_('record_variable "." field_selector')
    def structured_variable(self, p):
        pass

    @_('symbolic_variable')
    def record_variable(self, p):
        pass

    @_('IDENTIFIER')
    def field_selector(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}


##########################################
# B.1.4.3 Declaration and initialization #
##########################################

    @_('VAR_INPUT [ RETAIN ] input_declaration ";" { input_declaration ";" } END_VAR',
       'VAR_INPUT [ NON_RETAIN ] input_declaration ";" { input_declaration ";" } END_VAR')
    def input_declarations(self, p):
        if p[3] == ';':
            return { "name": self.production.name, "value": p[1][0], "children": [ p[2] ] }
        return { "name": self.production.name, "value": p[1][0], "children": [ p[2], p[3] ] }

    @_('var_init_decl', 'edge_declaration')
    def input_declaration(self, p):
        return { "name": self.production.name, "children": [ p[0] ] }

    @_('var1_list ":" BOOL R_EDGE',
       'var1_list ":" BOOL F_EDGE')
    def edge_declaration(self, p):
        pass

    @_('var1_init_decl', 'array_var_init_decl',
        'structured_var_init_decl', 'fb_name_decl', 'string_var_declaration')
    def var_init_decl(self, p):
        return { "name": self.production.name, "children": [ p[0] ] }

    @_('var1_list ":" simple_spec_init',
       'var1_list ":" subrange_spec_init',
       'var1_list ":" enumerated_spec_init')
    def var1_init_decl(self, p):
        return { "name": self.production.name, "children": [ p[0], p[2] ] }

    @_('variable_name { "," variable_name }')
    def var1_list(self, p):
        items = [p[0]]
        for obj in p[1]:
            items.append(obj[1])

        return { "name": self.production.name, "children": items }

    @_('var1_list ":" array_spec_init')
    def array_var_init_decl(self, p):
        pass

    @_('var1_list ":" initialized_structure')
    def structured_var_init_decl(self, p):
        pass

    @_('fb_name_list ":" function_block_type_name [ ASSIGN structure_initialization ]')
    def fb_name_decl(selp, p):
        pass

    @_('fb_name { "," fb_name }')
    def fb_name_list(self, p):
        pass

    @_('IDENTIFIER')
    def fb_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('VAR_OUTPUT var_init_decl ";"  { var_init_decl ";" } END_VAR',
       'VAR_OUTPUT RETAIN var_init_decl ";"  { var_init_decl ";" } END_VAR',
       'VAR_OUTPUT NON_RETAIN var_init_decl ";"  { var_init_decl ";" } END_VAR')
    def output_declarations(self, p):
        pass

    @_('VAR_IN_OUT var_declaration ";"  { var_declaration ";" } END_VAR')
    def input_output_declarations(self, p):
        pass

    @_('temp_var_decl', 'fb_name_decl')
    def var_declaration(self, p):
        pass

    @_('var1_declaration', 'array_var_declaration',
       'structured_var_declaration', 'string_var_declaration')
    def temp_var_decl(self, p):
        pass

    @_('var1_list ":" simple_specification',
       'var1_list ":" subrange_specification',
       'var1_list ":" enumerated_specification')
    def var1_declaration(self, p):
        pass

    @_('var1_list ":" array_specification')
    def array_var_declaration(self, p):
        pass

    @_('var1_list ":" structure_type_name')
    def structured_var_declaration(self, p):
        pass

    @_('VAR [ CONSTANT ] var_init_decl ";" { var_init_decl ";" } END_VAR')
    def var_declarations(self, p):
        pass

    @_('VAR RETAIN var_init_decl ";" { var_init_decl ";" } END_VAR')
    def retentive_var_declarations(self, p):
        pass

    @_('VAR [ CONSTANT ] located_var_decl ";" { located_var_decl ";" } END_VAR',
       'VAR [ RETAIN ] located_var_decl ";" { located_var_decl ";" } END_VAR',
       'VAR [ NON_RETAIN ] located_var_decl ";" { located_var_decl ";" } END_VAR')
    def located_var_declarations(self, p):
        pass

    @_('[ variable_name ] location ":" located_var_spec_init')
    def located_var_decl(self, p):
        pass

    @_('VAR_EXTERNAL [ CONSTANT ] external_declaration ";" { external_declaration ";" } END_VAR')
    def external_var_declarations(self, p):
        pass

    @_('global_var_name ":" simple_specification',
       'global_var_name ":" subrange_specification',
       'global_var_name ":" enumerated_specification',
       'global_var_name ":" array_specification',
       'global_var_name ":" structure_type_name',
       'global_var_name ":" function_block_type_name'
        )
    def external_declaration(self, p):
        pass

    @_('IDENTIFIER')
    def global_var_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('VAR_GLOBAL [ CONSTANT ] global_var_decl ";" { global_var_decl ";" } END_VAR',
       'VAR_GLOBAL [ RETAIN ] global_var_decl ";" { global_var_decl ";" } END_VAR')
    def global_var_declarations(self, p):
        pass

    @_('global_var_spec ":" located_var_spec_init',
       'global_var_spec ":" function_block_type_name')
    def global_var_decl(self, p):
        pass

    @_('global_var_list', '[ global_var_name ] location')
    def global_var_spec(self, p):
        pass

    @_('simple_spec_init', 'subrange_spec_init',
       'enumerated_spec_init', 'array_spec_init', 'initialized_structure',
       'single_byte_string_spec','double_byte_string_spec')
    def located_var_spec_init(self, p):
        pass

    @_('AT direct_variable')
    def location(self, p):
        pass

    @_('global_var_name { "," global_var_name }')
    def global_var_list(self, p):
        pass

    @_('single_byte_string_var_declaration',
       'double_byte_string_var_declaration')
    def string_var_declaration(self, p):
        pass

    @_('var1_list ":" single_byte_string_spec')
    def single_byte_string_var_declaration(self, p):
        pass

    @_('STRING [ "[" integer "]" ] [ ASSIGN single_byte_character_string ]')
    def single_byte_string_spec(self, p):
        pass

    @_('var1_list ":" double_byte_string_spec')
    def double_byte_string_var_declaration(self, p):
        pass

    @_('WSTRING [ "[" integer "]" ] [ ASSIGN double_byte_character_string ]')
    def double_byte_string_spec(self, p):
        pass

    @_('VAR [ RETAIN ] incompl_located_var_decl ";" { incompl_located_var_decl ";" } END_VAR',
       'VAR [ NON_RETAIN ] incompl_located_var_decl ";" { incompl_located_var_decl ";" } END_VAR')
    def incompl_located_var_declarations(self, p):
        pass

    @_('variable_name incompl_location ":" var_spec')
    def incompl_located_var_decl(self, p):
        pass

    @_('AT "%" "I" "*"',
       'AT "%" "Q" "*"',
       'AT "%" "M" "*"')
    def incompl_location(self, p):
        pass

    @_('simple_specification',
       'subrange_specification', 'enumerated_specification',
       'array_specification', 'structure_type_name',
       'STRING [ "[" integer "]" ]', 'WSTRING [ "[" integer "]" ]')
    def var_spec(self, p):
        pass

####################################
# B.1.5 Program organization units #
####################################

#####################
# B.1.5.1 Functions #
#####################

    @_('standard_function_name', 'derived_function_name')
    def function_name(self, p):
        return { "name": self.production.name, "children": [ p[0] ] }

    @_('STANDARD_FUNCTION_NAME')
    def standard_function_name(self, p):
        return { "name": self.production.name, "value": p[0], "children": [ None ] }

    @_('IDENTIFIER')
    def derived_function_name(self, p):
        return { "name": self.production.name, "value": p[0], "children": [ None ] }

    @_('FUNCTION derived_function_name ":" elementary_type_name io_OR_function_var_declarations_list function_body END_FUNCTION',
       'FUNCTION derived_function_name ":" derived_type_name io_OR_function_var_declarations_list function_body END_FUNCTION')
    def function_declaration(self, p):
        return { "name": self.production.name, "children": [ p[1], p[3], p[4], p[5] ] }

    @_('io_var_declarations', 'function_var_decls', 'io_OR_function_var_declarations_list io_var_declarations', 'io_OR_function_var_declarations_list function_var_decls')
    def io_OR_function_var_declarations_list(self, p):
        items = []
        for obj in p:
            items.append(obj)
        return { "name": self.production.name, "children": items }

    @_('input_declarations', 'output_declarations', 
       'input_output_declarations')
    def io_var_declarations(self, p):
        return { "name": self.production.name, "children": [ p[0] ] }

    @_('VAR [ CONSTANT ] var2_init_decl ";" { var2_init_decl ";" } END_VAR')
    def function_var_decls(self, p):
        pass

    @_('instruction_list', 'statement_list')
    def function_body(self, p):
        return { "name": self.production.name, "children": [ p[0] ] }

    @_('var1_init_decl', 'array_var_init_decl',
       'structured_var_init_decl', 'string_var_declaration')
    def var2_init_decl(self, p):
        pass

###########################
# B.1.5.2 Function blocks #
###########################
    @_('standard_function_block_name',
       'derived_function_block_name')
    def function_block_type_name(self, p):
        pass

    @_('STANDARD_FUNCTION_BLOCK_NAME')
    def standard_function_block_name(self, p):
        pass

    @_('IDENTIFIER')
    def derived_function_block_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('FUNCTION_BLOCK derived_function_block_name { io_var_declarations } function_block_body END_FUNCTION_BLOCK',
       'FUNCTION_BLOCK derived_function_block_name { other_var_declarations } function_block_body END_FUNCTION_BLOCK')
    def function_block_declaration(self, p):
        pass

    #NOTE: replaced non_retentive_var_declaclarations to non_retentive_var_decls
    @_('external_var_declarations', 'var_declarations',
       'retentive_var_declarations', 'non_retentive_var_decls',
       'temp_var_decls', 'incompl_located_var_declarations')
    def other_var_declarations(self, p):
        pass

    @_('VAR_TEMP temp_var_decl ";" { temp_var_decl ";" } END_VAR')
    def temp_var_decls(self, p):
        pass

    @_('VAR NON_RETAIN var_init_decl ";" { var_init_decl ";" } END_VAR')
    def non_retentive_var_decls(self, p):
        pass

    @_('sequential_function_chart',
       'instruction_list', 'statement_list')
    def function_block_body(self, p):
        pass

####################
# B.1.5.3 Programs #
####################
    @_('IDENTIFIER')
    def program_type_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('PROGRAM program_type_name { io_var_declarations } function_block_body END_PROGRAM',
       'PROGRAM program_type_name { other_var_declarations } function_block_body END_PROGRAM',
       'PROGRAM program_type_name { located_var_declarations } function_block_body END_PROGRAM',
       'PROGRAM program_type_name { program_access_decls } function_block_body END_PROGRAM')
    def program_declaration(self, p):
        pass

    @_('VAR_ACCESS program_access_decl ";" { program_access_decl ";" } END_VAR')
    def program_access_decls(self, p):
        pass

    @_('access_name ":" symbolic_variable ":" non_generic_type_name [ direction ]')
    def program_access_decl(self, p):
        pass

############################################
# B.1.6 Sequential function chart elements #
############################################
    @_('sfc_network { sfc_network }')
    def sequential_function_chart(self, p):
        pass

    @_('initial_step { step }',
       'initial_step { transition }',
       'initial_step { action }')
    def sfc_network(self, p):
        pass

    @_('INITIAL_STEP step_name ":" { action_association ";" } END_STEP')
    def initial_step(self, p):
        pass

    @_('STEP step_name ":" { action_association ";" } END_STEP')
    def step(self, p):
        pass

    @_('IDENTIFIER')
    def step_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('action_name "(" [ action_qualifier ] { "," indicator_name } ")"')
    def action_association(self, p):
        pass

    @_('IDENTIFIER')
    def action_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('"N"', '"R"', '"S"', '"P"', 'timed_qualifier "," action_time')
    def action_qualifier(self, p):
        pass

    @_('"L"', '"D"', 'SD', 'DS', 'SL')
    def timed_qualifier(self, p):
        pass

    @_('duration', 'variable_name')
    def action_time(self, p):
        pass

    @_('variable_name')
    def indicator_name(self, p):
        pass

    @_('TRANSITION [ transition_name ] [ "(" PRIORITY ASSIGN integer ")" ] FROM steps TO steps transition_condition END_TRANSITION')
    def transition(self, p):
        pass

    @_('IDENTIFIER')
    def transition_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('step_name', '"(" step_name "," step_name { "," step_name } ")"')
    def steps(self, p):
        pass

    #NOTE: replace simple_instruction_list to simple_instr_list
    @_('":" simple_instr_list', 'ASSIGN expression ";"')
    def transition_condition(self, p):
        pass

    @_('ACTION action_name ":" function_block_body END_ACTION')
    def action(self, p):
        pass

################################
# B.1.7 Configuration elements #
################################
    @_('IDENTIFIER')
    def configuration_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('IDENTIFIER')
    def resource_type_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('CONFIGURATION configuration_name [ global_var_declarations ] single_resource_declaration [ access_declarations ] [ instance_specific_initializations ] END_CONFIGURATION',
       'CONFIGURATION configuration_name [ global_var_declarations ] resource_declaration { resource_declaration } [ access_declarations ] [ instance_specific_initializations ] END_CONFIGURATION')
    def configuration_declaration(self, p):
        pass

    @_('RESOURCE resource_name ON resource_type_name [ global_var_declarations ] single_resource_declaration END_RESOURCE')
    def resource_declaration(self, p):
        pass

    @_('{ task_configuration ";" } program_configuration ";" { program_configuration ";" }')
    def single_resource_declaration(self, p):
        pass

    @_('IDENTIFIER')
    def resource_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('VAR_ACCESS access_declaration ";" { access_declaration ";" } END_VAR')
    def access_declarations(self, p):
        pass

    @_('access_name ":" access_path ":" non_generic_type_name [ direction ]')
    def access_declaration(self, p):
        pass

    @_('[ resource_name "." ] direct_variable',
       '[ resource_name "." ] [ program_name "." ] { fb_name "." } symbolic_variable')
    def access_path(self, p):
        pass

    @_('[ resource_name "." ] global_var_name [ "." structure_element_name ]')
    def global_var_reference(self, p):
        pass

    @_('IDENTIFIER')
    def access_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('program_name "." symbolic_variable')
    def program_output_reference(self, p):
        pass

    @_('IDENTIFIER')
    def program_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('READ_WRITE', 'READ_ONLY')
    def direction(self, p):
        pass

    @_('TASK task_name task_initialization')
    def task_configuration(self, p):
        pass

    @_('IDENTIFIER')
    def task_name(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('"(" [ SINGLE ASSIGN data_source "," ] [ INTERVAL ASSIGN data_source "," ] PRIORITY ASSIGN integer ")"')
    def task_initialization(self, p):
        pass

    @_('constant', 'global_var_reference', 'program_output_reference', 'direct_variable')
    def data_source(self, p):
        pass

    @_('PROGRAM [ RETAIN ] program_name [ WITH task_name ] ":" program_type_name [ "(" prog_conf_elements ")" ]',
       'PROGRAM [ NON_RETAIN ] program_name [ WITH task_name ] ":" program_type_name [ "(" prog_conf_elements ")" ]')
    def program_configuration(self, p):
        pass

    @_('prog_conf_element { "," prog_conf_element }')
    def prog_conf_elements(self, p):
        pass

    @_('fb_task', 'prog_cnxn')
    def prog_conf_element(self, p):
        pass

    @_('fb_name WITH task_name')
    def fb_task(self, p):
        pass

    @_('symbolic_variable ASSIGN prog_data_source',
       'symbolic_variable SENDTO data_sink')
    def prog_cnxn(self, p):
        pass

    @_('constant', 'enumerated_value', 'global_var_reference', 'direct_variable')
    def prog_data_source(self, p):
        pass

    @_('global_var_reference', 'direct_variable')
    def data_sink(self, p):
        pass

    @_('VAR_CONFIG instance_specific_init ";" { instance_specific_init ";" } END_VAR')
    def instance_specific_initializations(self, p):
        pass

    @_('resource_name "." program_name "." { fb_name "." } variable_name [ location ] ":" located_var_spec_init',
       'resource_name "." program_name "." { fb_name "." } fb_name ":" function_block_type_name ASSIGN structure_initialization')
    def instance_specific_init(self, p):
        pass

######################################
# B.2 Language IL (Instruction List) #
######################################

###################################
# B.2.1 Instructions and operands #
###################################
    @_('il_instruction { il_instruction }')
    def instruction_list(self, p):
        pass

    @_('[ label ":" ] EOL { EOL }',
       '[ label ":" ] il_simple_operation EOL { EOL }',
       '[ label ":" ] il_expression EOL { EOL }',
       '[ label ":" ] il_jump_operation EOL { EOL }',
       '[ label ":" ] il_fb_call EOL { EOL }',
       '[ label ":" ] il_formal_funct_call EOL { EOL }',
       '[ label ":" ] il_return_operator EOL { EOL }')
    def il_instruction(self, p):
        pass

    @_('IDENTIFIER')
    def label(self, p):
        return {"name": self.production.name, "value": p[0], "children": [ None ]}

    @_('il_simple_operator [ il_operand ]',
       'function_name [ il_operand_list ]')
    def il_simple_operation(self, p):
        pass

    @_('il_expr_operator "(" [ il_operand ] EOL { EOL } [ simple_instr_list ] ")"')
    def il_expression(self, p):
        pass

    @_('il_jump_operator label')
    def il_jump_operation(self, p):
        pass

    @_('il_call_operator fb_name "(" ( EOL { EOL } [ il_param_list ] )  ")" ',
       'il_call_operator fb_name "("  [ il_operand_list ]  ")" ',
       'il_call_operator fb_name "(" ")"',
       'il_call_operator fb_name')
    def il_fb_call(self, p):
        pass

    @_('function_name "(" EOL { EOL } [ il_param_list ] ')
    def il_formal_funct_call(self, p):
        pass

    @_('constant', 'variable', 'enumerated_value')
    def il_operand(self, p):
        pass
    
    @_('il_operand { "," il_operand }')
    def il_operand_list(self, p):
        pass

    @_('il_simple_instruction { il_simple_instruction }')
    def simple_instr_list(self, p):
        pass

    @_('il_simple_operation EOL { EOL }', 'il_expression EOL { EOL }', 'il_formal_funct_call EOL { EOL }')
    def il_simple_instruction(self, p):
        pass

    @_('{ il_param_instruction } il_param_last_instruction')
    def il_param_list(self, p):
        pass

    @_('il_param_assignment "," EOL { EOL }', 'il_param_out_assignment "," EOL { EOL }')
    def il_param_instruction(self, p):
        pass

    @_('il_param_assignment EOL { EOL }', 'il_param_out_assignment  EOL { EOL }')
    def il_param_last_instruction(self, p):
        pass

    @_('il_assign_operator il_operand', 'il_assign_operator "(" EOL { EOL } simple_instr_list ")"')
    def il_param_assignment(self, p):
        pass

    @_('il_assign_out_operator variable')
    def il_param_out_assignment(self, p):
        pass

###################
# B.2.2 Operators #
###################

    @_('LD', 'LDN', 'ST', 'STN', 'NOT', 'S',
       'R', 'S1', 'R1', 'CLK', 'CU', 'CD', 'PV',
       'IN', 'PT', 'il_expr_operator')
    def il_simple_operator(self, p):
        pass

    @_('AND', '"&"', 'OR', 'XOR', 'ANDN', 'AN', 'ORN',
       'XORN', 'ADD', 'SUB', 'MUL', 'DIV', 'MOD', 'GT', 'GE', 'EQ',
       'LT','LE','NE')
    def il_expr_operator(self, p):
        pass

    @_('variable_name ASSIGN')
    def il_assign_operator(self, p):
        pass

    @_('[ NOT ] variable_name SENDTO')
    def il_assign_out_operator(self, p):
        pass

    @_('CAL', 'CALC', 'CALCN')
    def il_call_operator(self, p):
        pass

    @_('RET', 'RETC', 'RETCN')
    def il_return_operator(self, p):
        pass

    @_('JMP', 'JMPC', 'JMPCN')
    def il_jump_operator(self, p):
        pass

#####################################
# B.3 Language ST (Structured Text) #
#####################################

#####################
# B.3.1 Expressions #
#####################
    @_('xor_expression { OR xor_expression }')
    def expression(self, p):
        items = [p[0]]
        for obj in p[1]:
            items.append(obj[1])
        return { "name": self.production.name, "children": items }


    @_('and_expression  { XOR and_expression }')
    def xor_expression(self, p):
        items = [p[0]]
        for obj in p[1]:
            items.append(obj[1])
        return { "name": self.production.name, "children": items }

    @_('comparison { "&" comparison } ', 'comparison { AND comparison }')
    def and_expression(self, p):
        items = [p[0]]
        for obj in p[1]:
            items.append(obj[1])
        return { "name": self.production.name, "children": items }

    @_('equ_expression { "=" equ_expression }')
    def comparison(self, p):
        items = [p[0]]
        for obj in p[1]:
            items.append(obj[1])
        return { "name": self.production.name, "children": items }

    @_('add_expression { comparison_operator add_expression }')
    def equ_expression(self, p):
        items = [p[0]]
        for obj in p[1]:
            items.append(obj[1])
        return { "name": self.production.name, "children": items }

    @_('"<"', '">"', 'LE_EQ', 'GE_EQ')
    def comparison_operator(self, p):
        return { "name": self.production.name, "children": [ p[0] ] }

    @_('term { add_operator term } ')
    def add_expression(self, p):
        items = [p[0]]
        for obj in p[1]:
            items.append(obj[0])
            items.append(obj[1])

        return { "name": self.production.name, "children": items }

    @_('"+"', '"-"')
    def add_operator(self, p):
        return { "name": self.production.name, "value": p[0], "children": [ None ] }


    @_('power_expression { multiply_operator power_expression }')
    def term(self, p):
        items = [p[0]]
        for obj in p[1]:
            tmp = obj[1]
            tmp["value"] = obj[0]["value"]
            items.append(tmp)
        return { "name": self.production.name, "children": items }

    @_('"*"', '"/"', 'MOD')
    def multiply_operator(self, p):
        return { "name": self.production.name, "value": p[0], "children": [ None ] }

    @_('unary_expression { DOUBLESTAR unary_expression }')
    def power_expression(self, p):
        items = [p[0]]
        for obj in p[1]:
            tmp = obj[1]
            tmp["value"] = p.DOUBLESTAR
            items.append(tmp)
        return { "name": self.production.name, "children": items }

    @_('[ unary_operator ] primary_expression')
    def unary_expression(self, p):
        if p[0][0] == None:
            return { "name": self.production.name, "value": None, "children": [ p[1] ] }
        return { "name": self.production.name, "value": p[0]["value"], "children": [ p[1] ] }

    @_('"-"', 'NOT')
    def unary_operator(self, p):
        return { "name": self.production.name, "value": p[0], "children": [ None ] }

    @_('constant', 'enumerated_value', 'variable', '"(" expression ")"',
       'function_name "(" param_assignment { "," param_assignment } ")"')
    def primary_expression(self, p):
        if len(p) == 1:
            return { "name": self.production.name, "children": [ p[0] ] }
        elif p[0] == '(':
            return { "name": self.production.name, "children": [ p[1] ] }
        return { "name": self.production.name, "children": [ p[0], p[1], p[3] ] }

####################
# B.3.2 Statements #
####################
    @_('statement ";" { statement ";" }')
    def statement_list(self, p):
        items = [p[0]]
        for obj in p[2]:
            items.append(obj[0])
        return { "name": self.production.name, "children": items }

    @_('NIL', 'assignment_statement', 'subprogram_control_statement',
       'selection_statement', 'iteration_statement')
    def statement(self, p):
        return { "name": self.production.name, "children": [ p[0] ] }

#################################
# B.3.2.1 Assignment statements #
#################################
    @_('variable ASSIGN expression')
    def assignment_statement(self, p):
        return { "name": self.production.name, "children": [ p[0] , p[2] ] }

#########################################
# B.3.2.2 Subprogram control statements #
#########################################
    @_('fb_invocation', 'RETURN')
    def subprogram_control_statement(self, p):
        pass

    @_('fb_name "(" [ param_assignment { "," param_assignment } ]')
    def fb_invocation(self, p):
        pass

    @_('[ variable_name ASSIGN ] expression',
       '[ NOT ] variable_name SENDTO variable')
    def param_assignment(self, p):
        pass

################################
# B.3.2.3 Selection statements #
################################
    @_('if_statement', 'case_statement')
    def selection_statement(self, p):
        return { "name": self.production.name, "children": [ p[0] ] }

    @_('IF expression THEN statement_list elseif_statement_list [ else_statement ] END_IF')
    def if_statement(self, p):
        items = [p[1], p[3], p[4]]
        if p[5] != 'END_IF':
            items.append(p[5][0])
        return { "name": self.production.name, "children": items }

    @_('{ elseif_statement }')
    def elseif_statement_list(self, p):
        items = [ ]
        for obj in p[0]:
            items.append(obj[0])
        return { "name": self.production.name, "children": items }

    @_('ELSIF expression THEN statement_list')
    def elseif_statement(self, p):
        return { "name": self.production.name, "children": [ p[1], p[3] ] }

    @_('ELSE statement_list')
    def else_statement(self, p):
        return { "name": self.production.name, "children": [ p[1] ] }

    @_('CASE expression OF case_element { case_element } [ ELSE statement_list ] END_CASE')
    def case_statement(self, p):
        pass

    @_('case_list ":" statement_list')
    def case_element(self, p):
        pass

    @_('case_list_element { "," case_list_element }')
    def case_list(self, p):
        pass

    @_('subrange', 'signed_integer', 'enumerated_value')
    def case_list_element(self, p):
        pass

################################
# B.3.2.4 Iteration statements #
################################

    @_('for_statement', 'while_statement', 'repeat_statement', 'exit_statement')
    def iteration_statement(self, p):
        return { "name": self.production.name, "children": [ p[0] ] }

    @_('FOR control_variable ASSIGN for_list DO statement_list END_FOR')
    def for_statement(self, p):
        return { "name": self.production.name, "children": [ p[1], p[3], p[5] ] }

    @_('IDENTIFIER')
    def control_variable(self, p):
        pass
    
    @_('expression TO expression [ BY expression ]')
    def for_list(self, p):
        pass

    @_('WHILE expression DO statement_list END_WHILE')
    def while_statement(self, p):
        return { "name": self.production.name, "children": [ p[1], p[3] ] }

    @_('REPEAT statement_list UNTIL expression END_REPEAT')
    def repeat_statement(self, p):
        return { "name": self.production.name, "children": [ p[1], p[3] ] }

    @_('EXIT')
    def exit_statement(self, p):
        pass

    def error(self, p):
        print("Parsing error at token %s" % str(p))
        exit()
