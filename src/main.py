import argparse
from iec_lexer import IECLexer
from iec_parser import IECParser
from iec_generator_rust import RustCodeGenerator
from iec_generator_c import CCodeGenerator


def main():
    lexer = IECLexer()

    while True:
        #text = input(">>> ")
        text = '''
        function inter : INT 
        var_input 
            a_1, b_1: int; 
        end_var
            if a_1 = b_1 then
              a_1 := 70_9;
            elsif b_1 = 1 then
              b_1 := 10;
            end_if;
            inter := a_1 + b_1;
            while true do
               b1 := b1 + 1;
            end_while;
        end_function
        '''
        tokens = lexer.tokenize(text)
        # for tok in tokens:
        #    print('%r:%r %r\t{%r}' % (tok.lineno, tok.index, tok.type, tok.value))
        parser = IECParser()
        result = parser.parse(tokens)
        print(result)
        print("\n********\n")
        if (result != None):

            if args.gnd.strip() == "Rust":
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
