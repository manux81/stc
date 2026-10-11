# Bundled SLY lexer/parser engine

These `lex.py` and `yacc.py` sources are SLY by David M. Beazley, bundled with
STC. Copyright and redistribution terms are retained in each source header.
The exact upstream version is not recorded here.

STC imports `Lexer` from `lex.py` and `Parser` from `yacc.py`. IEC tokens and
grammar belong in `src/stc/parsing/lexer.py` and `src/stc/parsing/parser.py`.
This directory is for maintenance of the parser engine itself.
