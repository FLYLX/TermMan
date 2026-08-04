import ast, pathlib
src = pathlib.Path("backend/app/plugins/robot/prompts.py").read_text(encoding="utf-8")
tree = ast.parse(src)
ns = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        name = getattr(node.targets[0], "id", "")
        if name.startswith("ROBOT_"):
            try:
                ns[name] = eval(compile(ast.Expression(node.value), "<c>", "eval"), {}, ns)
            except Exception as e:
                print(name, "EVAL_FAIL", e)
for name, val in ns.items():
    if isinstance(val, str):
        print("="*10, name, "chars:", len(val))
        print(val.encode("unicode_escape").decode("ascii"))
