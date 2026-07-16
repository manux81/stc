class SemanticError(Exception):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__("\n".join(diagnostics))


class SemanticAnalyzer:
    def analyze(self, ast):
        diagnostics = []
        for function in self._find_nodes(ast, "function_declaration"):
            diagnostics.extend(self._check_function(function))
        if diagnostics:
            raise SemanticError(diagnostics)

    def _check_function(self, function):
        name = function["children"][0]["value"]
        declarations = {name}
        declarations.update(self._collect_section_names(function, "input_declarations"))
        declarations.update(self._collect_section_names(function, "function_var_decls"))

        diagnostics = []
        body = self._first_child(function, "function_body")
        for variable in self._find_nodes(body, "variable_name"):
            variable_name = variable["value"]
            if variable_name not in declarations:
                diagnostics.append(f"Undeclared variable '{variable_name}' in function '{name}'.")
        return diagnostics

    def _collect_section_names(self, node, section_name):
        names = set()
        for section in self._find_nodes(node, section_name):
            for declaration in self._find_nodes(section, "var1_init_decl"):
                var_list = self._first_child(declaration, "var1_list")
                for variable in self._find_nodes(var_list, "variable_name"):
                    names.add(variable["value"])
        return names

    def _find_nodes(self, node, name):
        if not isinstance(node, dict):
            return
        if node.get("name") == name:
            yield node
        for child in node.get("children", []):
            yield from self._find_nodes(child, name)

    def _first_child(self, node, name):
        if not isinstance(node, dict):
            return None
        for child in node.get("children", []):
            if isinstance(child, dict) and child.get("name") == name:
                return child
        return None
