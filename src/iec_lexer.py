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

import re
from sly import Lexer

class IECLexer(Lexer):
    def generate_standard_function_name():
        simple_type = {r'SINT', r'INT', r'DINT', r'LINT', r'USINT', r'UINT', r'UDINT', r'ULINT'}
        ret = r'( '
        for from_type in simple_type:
            for to_type in simple_type:
                if from_type != to_type:
                    ret += from_type + r'_TO_' + to_type + r' | '
        ret = ret[0: -2]
        ret += r')'
        return ret

    def generate_standard_function_block_name():
        ret = r'( R_TRIG | F_TRIG )'
        return ret

    reflags = re.IGNORECASE
    tokens = { 
	LETTER, DIGIT, OCTAL_DIGIT, HEX_DIGIT,
        IDENTIFIER, MINUS, PLUS, UNDERSCORE, 
        BIT, BINARY_INTEGER, OCTAL_INTEGER, HEX_INTEGER, INTEGER,
        TRUE,FALSE,
        MS, TIME,
    
        SINT, INT, DINT, LINT, USINT,
        UINT, UDINT, ULINT, REAL, LREAL, DATE, TIME_OF_DAY, TOD, DATE_AND_TIME,
        DT, BOOL, BYTE, WORD, DWORD, LWORD,

        ANY, ANY_DERIVED, ANY_ELEMENTARY, ANY_MAGNITUDE, ANY_NUM, ANY_REAL, ANY_INT, ANY_BIT, ANY_STRING, ANY_DATE,

        TYPE, END_TYPE, ASSIGN, DOTDOT, ARRAY, OF, STRUCT, END_STRUCT, STRING, WSTRING,

        VAR_INPUT, RETAIN, END_VAR, NON_RETAIN, R_EDGE, F_EDGE, VAR_OUTPUT, VAR_IN_OUT, VAR, CONSTANT, VAR_EXTERNAL, VAR_GLOBAL, AT,
        STANDARD_FUNCTION_NAME, FUNCTION, END_FUNCTION,

        STANDARD_FUNCTION_BLOCK_NAME, FUNCTION_BLOCK, END_FUNCTION_BLOCK, VAR_TEMP,
        PROGRAM, END_PROGRAM, VAR_ACCESS,

        INITIAL_STEP, END_STEP, STEP, SD, DS, SL, TRANSITION, PRIORITY, FROM, TO, END_TRANSITION, ACTION, END_ACTION,
    
        CONFIGURATION, END_CONFIGURATION, RESOURCE, ON, END_RESOURCE, READ_WRITE, READ_ONLY, TASK, SINGLE, INTERVAL, WITH, SENDTO, VAR_CONFIG
    }
    ignore = ' \t'


    LETTER = r'[A-Za-z]'
    DIGIT  = r'[0-9]'
    OCTAL_DIGIT = r'[0-7]'
    HEX_DIGIT = r'digit|[A-F]'.format(digit=DIGIT)

    IDENTIFIER = r'({letter}|([\_]({letter}|{digit})))(([\_]?({letter}|{digit}))*)'.format(letter=LETTER, digit=DIGIT)
    MINUS   = r'\-'
    PLUS    = r'\+'
    UNDERSCORE = r'\_'
    INTEGER = r'DIGIT([\_]DIGIT)?'
    BIT = r'(1|0)'
    BINARY_INTEGER = r'2#{bit}([\_])?({bit})*'.format(bit=BIT)
    OCTAL_INTEGER = r'8#{octal_digit}([\_])?({octal_digit})*'.format(octal_digit=OCTAL_DIGIT)
    HEX_INTEGER = r'16#{hex_digit}([_])?({hex_digit})*'.format(hex_digit=HEX_DIGIT)
############################
# B.1.2.1 Numeric literals #
############################
    TRUE = r'TRUE'
    FALSE = r'FALSE'
#######################
#  B.1.2.3.1 Duration #
#######################
    MS = r'ms'
    TIME = r'TIME'

##################################
#  B.1.3.1 Elementary data types #
##################################
    SINT = r'SINT' 
    INT = r'INT'
    DINT = r'DINT'
    LINT = r'LINT'
    USINT = r'USINT' 
    UINT = r'UINT'
    UDINT = r'UDINT'
    ULINT = r'ULINT'
    REAL = r'REAL'
    LREAL = r'LREAL'
    DATE = r'DATE'
    TIME_OF_DAY = r'TIME_OF_DAY'
    TOD = r'TOD'
    DATE_AND_TIME = r'DATE_AND_TIME'
    DT = r'DT'
    BOOL = r'BOOL'
    BYTE = r'BYTE'
    WORD = r'WORD'
    DWORD = r'DWORD'
    LWORD = r'LWORD'
    

###############################
#  B.1.3.2 Generic data types #
###############################
    ANY = r'ANY'
    ANY_DERIVED = r'ANY_DERIVED'
    ANY_ELEMENTARY = r'ANY_ELEMENTARY'
    ANY_MAGNITUDE = r'ANY_MAGNITUDE'
    ANY_NUM = r'ANY_NUM'
    ANY_REAL = r'ANY_REAL'
    ANY_INT = r'ANY_INT'
    ANY_BIT = r'ANY_BIT'
    ANY_STRING = r'ANY_STRING'
    ANY_DATE = r'ANY_DATE'


##############################
# B.1.3.3 Derived data types #
##############################
    TYPE = r'TYPE'
    END_TYPE = r'END_TYPE'
    ASSIGN = r':='
    DOTDOT = r'..'
    ARRAY = r'ARRAY'
    OF = r'OF'
    STRUCT = r'STRUCT'
    END_STRUCT = r'END_STRUCT'
    STRING = r'STRING'
    WSTRING = r'WSTRING'

    
##########################################
# B.1.4.3 Declaration and initialization #
##########################################
    VAR_INPUT = r'VAR_INPUT'
    RETAIN = r'RETAIN'
    END_VAR = r'END_VAR'
    NON_RETAIN = r'NON_RETAIN'
    R_EDGE = r'R_EDGE'
    F_EDGE = r'F_EDGE'
    VAR_OUTPUT = r'VAR_OUTPUT'
    VAR_IN_OUT = r'VAR_IN_OUT'
    VAR = r'VAR'
    CONSTANT = r'CONSTANT'
    VAR_EXTERNAL = r'VAR_EXTERNAL'
    VAR_GLOBAL = r'VAR_GLOBAL'
    AT = r'AT'

####################################
# B.1.5 Program organization units #
####################################

#####################
# B.1.5.1 Functions #
#####################
    STANDARD_FUNCTION_NAME = generate_standard_function_name()
    FUNCTION = r'FUNCTION'
    END_FUNCTION = r'END_FUNCTION'

###########################
# B.1.5.2 Function blocks #
###########################
    STANDARD_FUNCTION_BLOCK_NAME = generate_standard_function_block_name()
    FUNCTION_BLOCK = r'FUNCTION_BLOCK'
    END_FUNCTION_BLOCK = r'END_FUNCTION_BLOCK'
    VAR_TEMP = r'VAR_TEMP'

####################
# B.1.5.3 Programs #
####################
    PROGRAM = r'PROGRAM'
    END_PROGRAM = r'END_PROGRAM'
    VAR_ACCESS = r'VAR_ACCESS'

############################################
# B.1.6 Sequential function chart elements #
############################################
    INITIAL_STEP = r'INITIAL_STEP'
    END_STEP = r'END_STEP'
    STEP = r'STEP'
    SD = r'SD'
    DS = r'DS'
    SL = r'SL'
    TRANSITION = r'TRANSITION'
    PRIORITY = r'PRIORITY'
    FROM = r'FROM'
    TO = r'TO'
    END_TRANSITION = r'END_TRANSITION'
    ACTION = r'ACTION'
    END_ACTION = r'ACTION'

################################
# B.1.7 Configuration elements #
################################
    CONFIGURATION = r'CONFIGURATION'
    END_CONFIGURATION = r'END_CONFIGURATION'
    RESOURCE = r'RESOURCE'
    ON = r'ON'
    END_RESOURCE = r'END_RESOURCE'
    READ_WRITE = r'READ_WRITE'
    READ_ONLY = r'READ_ONLY'
    TASK = r'TASK'
    SINGLE = r'SINGLE'
    INTERVAL = r'INTERVAL'
    WITH = r'WITH'
    SENDTO = r'=>'
    VAR_CONFIG = r'VAR_CONFIG'



    








