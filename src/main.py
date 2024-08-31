import argparse
from iec_lexer import IECLexer
from iec_parser import IECParser
from iec_generator_rust import RustCodeGenerator
from iec_generator_c import CCodeGenerator
import json

def print_tree(node, indent=""):
    """
    Stampa un albero di nodi con 'name' in grassetto rosso, 'value' in grassetto blu, e 'children' in grassetto verde.

    Args:
        node (dict, list, or other): Il nodo da stampare, che può essere un dizionario, una lista, o un altro tipo di dato.
        indent (str): Stringa di indentazione per la visualizzazione gerarchica.
    """
    # Codici ANSI per i colori e il testo in grassetto
    RED_BOLD = "\033[1;31m"
    BLUE_BOLD = "\033[1;34m"
    GREEN_BOLD = "\033[1;32m"
    RESET = "\033[0m"

    if isinstance(node, dict):
        name = node.get('name', 'Unnamed')
        value = node.get('value', 'None')
        children = node.get('children', [])

        # Stampa con colori e formattazione
        print(f"{indent}{RED_BOLD}Name:{RESET} {name} "
              f"- {BLUE_BOLD}Value:{RESET} {value} "
              f"- {GREEN_BOLD}Children:{RESET} {len(children)}")

        for child in children:
            print_tree(child, indent + "  ")
    elif isinstance(node, list):
        for item in node:
            print_tree(item, indent)
    else:
        print(f"{indent}{node}")





def main():
    lexer = IECLexer()

    while True:
        #text = input(">>> ")
        text = '''
        function inter : INT 
        var_input 
            a_1, b_1: int; 
            test: BOOL;
        end_var
        var
            ff: int;
        end_var
            test := TRUE;
            if a_1 = b_1 then
              a_1 := 70_9;
            elsif b_1 = 1 then
              b_1 := INT#10;
            end_if;
            inter := a_1 + b_1;
            while true do
               b1 := b1 + REAL#+10.0e-1;
            end_while;
        end_function
        '''
        tokens = lexer.tokenize(text)
        # for tok in tokens:
        #    print('%r:%r %r\t{%r}' % (tok.lineno, tok.index, tok.type, tok.value))
        parser = IECParser()
        try:
            result = parser.parse(tokens)
        except SyntaxError as e:
            print(str(e))
            exit()
        # Pretty print the result
        if result:
            print_tree(result)
        else:
            print(parser.error)

        if result is not None:

            if args.gnd is not None and args.gnd.strip() == "Rust":
                generator = RustCodeGenerator()
            else:
                generator = CCodeGenerator()

            generator.visit(result)
            print(generator.text)
        else:
            print(parser.error)
        exit()


if __name__ == '__main__':
    # Initialize parser
    parser = argparse.ArgumentParser()
    # Adding optional argumegeneratorTypent
    # standard: iec61131-3:ed2, iec61131-3:ed3
    parser.add_argument(
        "-s", "--std", help="Assume that the input sources are for <standard>.")

    parser.add_argument(
        "-g", "--gnd", nargs='?', help="Assume that the output format is for <generator>.")

    parser.add_argument(
        "-v", "--version", help="Display compiler version information.", action='store_true')

    # Read arguments from command line
    args = parser.parse_args()

    if args.std:
        print("Diplaying Output as: % s" % args.std)
    if args.version:
        print("stc (structured text compiler) 0.1")
        quit()

    main()
