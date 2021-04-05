
import argparse
from iec_lexer import IECLexer
from iec_parser import IECParser

class NodeVisitor:
    def __init__(self):
        pass

    def visit(self, node):
    	#"""Call visit method for current node"""
        method = 'visit_' + node["name"]

        #print("CALL:" + method)
        visitor = getattr(self, method, self.generic_visit)
        visitor(node)

    def generic_visit(self, node):
        #"""Called if no explicit visitor function exists for a node."""
        for child in node["children"]:
            if child == None:
                continue
            self.visit(child)

    def accept(self, node, callback = None):
        for child in node["children"]:
            if child == None:
                continue
            if callback != None and not callback(child["name"]):
                continue
            self.visit(child)

class CodeGenerator(NodeVisitor):
    text = ""
    def __init__(self):
        pass

    def visit_input_declaration(self, node):
        self.accept(node)
        self.text += ";"

    def visit_var1_init_decl(self, node):
        self.accept(node, lambda name : name != 'var1_list')
        self.text += " "
        self.accept(node, lambda name : name == 'var1_list')

    def visit_var1_list(self, node):
        for child in node["children"]:
            self.visit(child)
            if child != node["children"][-1]:
                self.text += ","

    def visit_signed_integer_type_name(self, node):
            self.text += node["value"]

    def visit_variable_name(self, node):
        self.text += node["value"]




def main():
    lexer = IECLexer()

    while True:
        text = input(">>> ")
        tokens = lexer.tokenize(text)
        #for tok in tokens:
        #    print('type=%r, value=%r' % (tok.type, tok.value))
        parser = IECParser()
        result = parser.parse(tokens)
        print(result)
        if (result != None):
            generator = CodeGenerator()
            generator.visit(result)
            print(generator.text)



if __name__ == '__main__':
    # Initialize parser
    parser = argparse.ArgumentParser()
 
    # Adding optional argument 
    # standard: iec61131-3:ed2, iec61131-3:ed3
    parser.add_argument("-s", "--std", help = "Assume that the input sources are for <standard>.")
    parser.add_argument("-v", "--version", help = "Display compiler version information.", action = 'store_true')
 
    # Read arguments from command line
    args = parser.parse_args()
 
    if args.std:
        print("Diplaying Output as: % s" % args.std)
    if args.version:
        print("stc (structured text compiler) 0.1")
        quit()

    main()


