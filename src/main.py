
import argparse
from iec_lexer import IECLexer
from iec_parser import IECParser

class NodeVisitor:
    def __init__(self):
        pass

    def visit(self, node):
    	#"""Call visit method for current node"""
        if isinstance(node, tuple):
            method = 'visit_' + node[0]
        elif isinstance(node, str):
            method = 'visit_' + node
        else:
            raise Exception('Node is not a valid type.')
        print("CALL:" + method)
        visitor = getattr(self, method, self.generic_visit)
        visitor(node)

    def generic_visit(self, node):
        #"""Called if no explicit visitor function exists for a node."""
        if isinstance(node[1], list):
            for item in node[1]:
                self.visit(item)
        elif isinstance(node[1], tuple):
            self.visit(node[1])

class CodeGenerator(NodeVisitor):

    def __init__(self):
        pass

    def visit_table(self, node):
        print(node[1])

    def visit_user(self, node):
        print(node[1])



def main():
    lexer = IECLexer()

    while True:
        text = input(">>> ")
        tokens = lexer.tokenize(text)
        #for tok in tokens:
        #    print('type=%r, value=%r' % (tok.type, tok.value))
        parser = IECParser()
        result = parser.parse(tokens)
        print (result)
        generator = CodeGenerator()
        generator.visit(result)



if __name__ == '__main__':
    # Initialize parser
    parser = argparse.ArgumentParser()
 
    # Adding optional argument 
    # standard: iec61131-3:ed2, iec61131-3:ed3
    parser.add_argument("-s", "--std", help = "Assume that the input sources are for <standard>.")
 
    # Read arguments from command line
    args = parser.parse_args()
 
    if args.std:
        print("Diplaying Output as: % s" % args.std)

    main()


