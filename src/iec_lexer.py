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
from typing import SupportsInt
from lex import Lexer

def generate_standard_function_name():
    simple_type = {r'SINT', r'INT', r'DINT', r'LINT', r'USINT', r'UINT', r'UDINT', r'ULINT'}
    ret = r'('
    for from_type in simple_type:
        for to_type in simple_type:
            if from_type != to_type:
                ret += from_type + r'_TO_' + to_type + r'|'
    ret = ret[0: -2]
    ret += r')'
    return ret

def generate_standard_function_block_name():
    ret = r'(R_TRIG|F_TRIG)'
    return ret

STD_FUN = generate_standard_function_name()
STD_FUN_BLK = generate_standard_function_block_name()

LETTER = r'[a-zA-Z]'
DIGIT  = r'[0-9]'
OCTAL_DIGIT = r'[0-7]'



class IECLexer(Lexer):
    reflags = re.IGNORECASE
    literals = { ':', ',', ';', '+', '-', '(', ')', '=' }
    ignore = ' \t'

    # Ignored pattern
    ignore_newline = r'\n+'

    # Extra action for newlines
    def ignore_newline(self, t):
        self.lineno += t.value.count('\n')

    tokens = { 
        IDENTIFIER,
        #LETTER, DIGIT, 
        OCTAL_DIGIT, HEX_DIGIT,
        MINUS, PLUS, UNDERSCORE,
        BIT, BINARY_INTEGER, OCTAL_INTEGER, HEX_INTEGER, INTEGER,
        TRUE,FALSE,

        DOLLAR_APC, DOLLAR_QOT, PRINTABLE_CHAR, DOLLAR_DOLLAR, DOLLAR_L, DOLLAR_N, DOLLAR_P,

        MS, TIME,
    
        SINT, INT, DINT, LINT, USINT,
        UINT, UDINT, ULINT, REAL, LREAL, DATE, TIME_OF_DAY, TOD, DATE_AND_TIME,
        DT, BOOL, BYTE, WORD, DWORD, LWORD,

        ANY, ANY_DERIVED, ANY_ELEMENTARY, ANY_MAGNITUDE, ANY_NUM, ANY_REAL, ANY_INT, ANY_BIT, ANY_STRING, ANY_DATE,

        TYPE, END_TYPE, ASSIGN, DOTDOT, ARRAY, OF, STRUCT, END_STRUCT, STRING, WSTRING,

        NIL,

        VAR_INPUT, RETAIN, END_VAR, NON_RETAIN, R_EDGE, F_EDGE, VAR_OUTPUT, VAR_IN_OUT, VAR, CONSTANT, VAR_EXTERNAL, VAR_GLOBAL, AT,
        STANDARD_FUNCTION_NAME, FUNCTION, END_FUNCTION,

        STANDARD_FUNCTION_BLOCK_NAME, FUNCTION_BLOCK, END_FUNCTION_BLOCK, VAR_TEMP,
        PROGRAM, END_PROGRAM, VAR_ACCESS,

        INITIAL_STEP, END_STEP, STEP, SD, DS, SL, TRANSITION, PRIORITY, FROM, TO, END_TRANSITION, ACTION, END_ACTION,
    
        CONFIGURATION, END_CONFIGURATION, RESOURCE, ON, END_RESOURCE, READ_WRITE, READ_ONLY, TASK, SINGLE, INTERVAL, WITH, SENDTO, VAR_CONFIG,

        EOL,

        LD, LDN, ST, STN, NOT, S, R, S1, R1, CLK, CU, CD, PV, IN, PT, AND, OR, XOR, ANDN, AN, ORN, XORN, ADD, SUB, MUL, DIV, MOD, GT, GE, EQ, LT, LE, NE, CAL, CALC, CALCN, RET, RETC, RETCN, JMP, JMPC, JMPCN,

        GE_EQ, LE_EQ, DOUBLESTAR,

        RETURN,

        IF, THEN, ELSIF, ELSE, END_IF, CASE, END_CASE,

        FOR, DO, END_FOR, BY, WHILE, END_WHILE, REPEAT, UNTIL, END_REPEAT, EXIT

    }

    STANDARD_FUNCTION_NAME = generate_standard_function_name()
    STANDARD_FUNCTION_BLOCK_NAME = generate_standard_function_block_name()
    IDENTIFIER = r'([a-zA-Z]|([\_]([a-zA-Z]|[0-9])))(([\_]?([a-zA-Z]|[0-9]))+)'

 
############################
# B.1.2.1 Numeric literals #
############################
    IDENTIFIER['TRUE'] = TRUE
    IDENTIFIER['FALSE'] = FALSE

##############################
#  B.1.2.2 Character strings #
##############################
    DOLLAR_APC = r'\$\''
    DOLLAR_QOT = r'\$"'
    PRINTABLE_CHAR = r'ppppppp'
    DOLLAR_DOLLAR = r'\$\$'
    DOLLAR_L = r'\$L'
    DOLLAR_N = r'\$N'
    DOLLAR_P = r'\$P'

#######################
#  B.1.2.3.1 Duration #
#######################
    IDENTIFIER['MS'] = MS
    IDENTIFIER['TIME'] = TIME

##################################
#  B.1.3.1 Elementary data types #
##################################
    IDENTIFIER['SINT'] = SINT
    IDENTIFIER['INT'] = INT
    IDENTIFIER['DINT'] = DINT
    IDENTIFIER['LINT'] = LINT
    IDENTIFIER['USINT'] = USINT
    IDENTIFIER['UINT'] = UINT
    IDENTIFIER['UDINT'] = UDINT
    IDENTIFIER['ULINT'] = ULINT
    IDENTIFIER['REAL'] = REAL
    IDENTIFIER['LREAL'] = LREAL
    IDENTIFIER['DATE'] = DATE
    IDENTIFIER['TIME_OF_DAY'] = TIME_OF_DAY
    IDENTIFIER['TOD'] = TOD
    IDENTIFIER['DATE_AND_TIME'] = DATE_AND_TIME
    IDENTIFIER['DT'] = DT
    IDENTIFIER['BOOL'] = BOOL
    IDENTIFIER['BYTE'] = BYTE
    IDENTIFIER['WORD'] = WORD
    IDENTIFIER['DWORD'] = DWORD
    IDENTIFIER['LWORD'] = LWORD
    

###############################
#  B.1.3.2 Generic data types #
###############################
    IDENTIFIER['ANY'] = ANY
    IDENTIFIER['ANY_DERIVED'] = ANY_DERIVED
    IDENTIFIER['ANY_ELEMENTARY'] = ANY_ELEMENTARY
    IDENTIFIER['ANY_MAGNITUDE'] = ANY_MAGNITUDE
    IDENTIFIER['ANY_NUM'] = ANY_NUM
    IDENTIFIER['ANY_REAL'] = ANY_REAL
    IDENTIFIER['ANY_INT'] = ANY_INT
    IDENTIFIER['ANY_BIT'] = ANY_BIT
    IDENTIFIER['ANY_STRING'] = ANY_STRING
    IDENTIFIER['ANY_DATE'] = ANY_DATE


##############################
# B.1.3.3 Derived data types #
##############################
    IDENTIFIER['TYPE'] = TYPE
    IDENTIFIER['END_TYPE'] = END_TYPE
    ASSIGN = r':='
    DOTDOT = r'\.\.'
    IDENTIFIER['ARRAY'] = ARRAY
    IDENTIFIER['OF'] = OF
    IDENTIFIER['STRUCT'] = STRUCT
    IDENTIFIER['END_STRUCT'] = END_STRUCT
    IDENTIFIER['STRING'] = STRING
    IDENTIFIER['WSTRING'] = WSTRING

###########################################
# B.1.(4.1 Directly represented variables #
###########################################
    NIL = r'\"\"'
    
##########################################
# B.1.4.3 Declaration and initialization #
##########################################
    IDENTIFIER['VAR_INPUT'] = VAR_INPUT
    IDENTIFIER['RETAIN'] = RETAIN
    IDENTIFIER['END_VAR'] = END_VAR
    IDENTIFIER['NON_RETAIN'] = NON_RETAIN
    IDENTIFIER['R_EDGE'] = R_EDGE
    IDENTIFIER['F_EDGE'] = F_EDGE
    IDENTIFIER['VAR_OUTPUT'] = VAR_OUTPUT
    IDENTIFIER['VAR_IN_OUT'] = VAR_IN_OUT
    IDENTIFIER['VAR'] = VAR
    IDENTIFIER['CONSTANT'] = CONSTANT
    IDENTIFIER['VAR_EXTERNAL'] = VAR_EXTERNAL
    IDENTIFIER['VAR_GLOBAL'] = VAR_GLOBAL
    IDENTIFIER['AT'] = AT

####################################
# B.1.5 Program organization units #
####################################

#####################
# B.1.5.1 Functions #
#####################
    IDENTIFIER['FUNCTION'] = FUNCTION
    IDENTIFIER['END_FUNCTION'] = END_FUNCTION

###########################
# B.1.5.2 Function blocks #
###########################
    IDENTIFIER['FUNCTION_BLOCK'] = FUNCTION_BLOCK
    IDENTIFIER['END_FUNCTION_BLOCK'] = END_FUNCTION_BLOCK
    IDENTIFIER['VAR_TEMP'] = VAR_TEMP

####################
# B.1.5.3 Programs #
####################
    IDENTIFIER['PROGRAM'] = PROGRAM
    IDENTIFIER['END_PROGRAM'] = END_PROGRAM
    IDENTIFIER['VAR_ACCESS'] = VAR_ACCESS

############################################
# B.1.6 Sequential function chart elements #
############################################
    IDENTIFIER['INITIAL_STEP'] = INITIAL_STEP
    IDENTIFIER['END_STEP'] = END_STEP
    IDENTIFIER['STEP'] = STEP
    IDENTIFIER['SD'] = SD
    IDENTIFIER['DS'] = DS
    IDENTIFIER['SL'] = SL
    IDENTIFIER['TRANSITION'] = TRANSITION
    IDENTIFIER['PRIORITY'] = PRIORITY
    IDENTIFIER['FROM'] = FROM
    IDENTIFIER['TO'] = TO
    IDENTIFIER['END_TRANSITION'] = END_TRANSITION
    IDENTIFIER['ACTION'] = ACTION
    IDENTIFIER['END_ACTION'] = END_ACTION

################################
# B.1.7 Configuration elements #
################################
    IDENTIFIER['CONFIGURATION'] = CONFIGURATION
    IDENTIFIER['END_CONFIGURATION'] = END_CONFIGURATION
    IDENTIFIER['RESOURCE'] = RESOURCE
    IDENTIFIER['ON'] = ON
    IDENTIFIER['END_RESOURCE'] = END_RESOURCE
    IDENTIFIER['READ_WRITE'] = READ_WRITE
    IDENTIFIER['READ_ONLY'] = READ_ONLY
    IDENTIFIER['TASK'] = TASK
    IDENTIFIER['SINGLE'] = SINGLE
    IDENTIFIER['INTERVAL'] = INTERVAL
    IDENTIFIER['WITH'] = WITH
    SENDTO = r'=>'
    IDENTIFIER['VAR_CONFIG'] = VAR_CONFIG

######################################
# B.2 Language IL (Instruction List) #
######################################

###################################
# B.2.1 Instructions and operands #
###################################
    EOL = r'\u2029'

###################
# B.2.2 Operators #
###################

    IDENTIFIER['LD'] = LD
    IDENTIFIER['LDN'] = LDN
    IDENTIFIER['ST'] = ST
    IDENTIFIER['STN'] = STN
    IDENTIFIER['NOT'] = NOT
    IDENTIFIER['S'] = S
    IDENTIFIER['R'] = R
    IDENTIFIER['S1'] = S1
    IDENTIFIER['R1'] = R1
    IDENTIFIER['CLK'] = CLK
    IDENTIFIER['CU'] = CU
    IDENTIFIER['CD'] = CD
    IDENTIFIER['PV'] = PV
    IDENTIFIER['IN'] = IN
    IDENTIFIER['PT'] = PT
    IDENTIFIER['AND'] = AND
    IDENTIFIER['OR'] = OR
    IDENTIFIER['XOR'] = XOR
    IDENTIFIER['ANDN'] = ANDN
    IDENTIFIER['&N'] = AN
    IDENTIFIER['ORN'] = ORN
    IDENTIFIER['XORN'] = XORN
    IDENTIFIER['ADD'] = ADD
    IDENTIFIER['SUB'] = SUB
    IDENTIFIER['MUL'] = MUL
    IDENTIFIER['DIV'] = DIV
    IDENTIFIER['MOD'] = MOD
    IDENTIFIER['GT'] = GT
    IDENTIFIER['GE'] = GE
    IDENTIFIER['EQ'] = EQ
    IDENTIFIER['LT'] = LT
    IDENTIFIER['LE'] = LE
    IDENTIFIER['NE'] = NE
    IDENTIFIER['CAL'] = CAL
    IDENTIFIER['CALC'] = CALC
    IDENTIFIER['CALCN'] = CALCN
    IDENTIFIER['RET'] = RET
    IDENTIFIER['RETC'] = RETC
    IDENTIFIER['RETCN'] = RETCN
    IDENTIFIER['JMP'] = JMP
    IDENTIFIER['JMPC'] = JMPC
    IDENTIFIER['JMPCN'] = JMPCN

#####################
# B.3.1 Expressions #
#####################
    GE_EQ = r'>='
    LE_EQ = r'<='
    DOUBLESTAR = r'\*\*'

#########################################
# B.3.2.2 Subprogram control statements #
#########################################
    IDENTIFIER['RETURN'] = RETURN

################################
# B.3.2.3 Selection statements #
################################
    IDENTIFIER['IF'] = IF
    IDENTIFIER['THEN'] = THEN
    IDENTIFIER['ELSIF'] = ELSIF
    IDENTIFIER['ELSE'] = ELSE
    IDENTIFIER['END_IF'] = END_IF
    IDENTIFIER['CASE'] = CASE
    IDENTIFIER['END_CASE'] = END_CASE



    IDENTIFIER['FOR'] = FOR
    IDENTIFIER['DO'] = DO
    IDENTIFIER['END_FOR'] = END_FOR
    IDENTIFIER['BY'] = BY
    IDENTIFIER['WHILE'] = WHILE
    IDENTIFIER['END_WHILE'] = END_WHILE
    IDENTIFIER['REPEAT'] = REPEAT
    IDENTIFIER['UNTIL'] = UNTIL
    IDENTIFIER['END_REPEAT'] = END_REPEAT
    IDENTIFIER['EXIT'] = EXIT

    HEX_DIGIT = r'[0-9]|[A-F]'
    #MINUS   = r'\-'
    #PLUS    = r'\+'
    UNDERSCORE = r'\_'
    INTEGER = r'[0-9]([\_][0-9])?'
    BIT = r'(1|0)'
    BINARY_INTEGER = r'2#(1|0)([\_])?((1|0))*'
    OCTAL_INTEGER = r'8#[0-7]([\_])?([0-7])*'
    HEX_INTEGER = r'16#[0-9]|[A-F]([_])?([0-9]|[A-F])*'




    








