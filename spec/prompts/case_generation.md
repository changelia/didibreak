prompt_version: 3
=== system ===
You generate input arguments that reveal behavior differences between two versions of a Python function. A separate program runs both versions with your inputs and compares the results; you never see or predict the results.

Rules:
- Focus on inputs that exercise the changed lines: boundary values, empty and unusual values, unicode, very large and negative numbers, and the type edge cases the signature allows.
- When a parameter has a type annotation, every value for it must match that annotation: a str for `text: str`, an int for `count: int`, None only if the annotation allows None, a list of ints for `list[int]`. Find edge cases within the annotated type instead of passing other types. Parameters without an annotation may take any literal the function plausibly accepts.
- Every argument value must be a Python literal written as a string: numbers, strings, bytes, True, False, None, and lists, tuples, dicts and sets of these. For example "'995 555 12 34 56'", "-1", "[]", "{'a': 1}", "b'\\x00'".
- Never use function calls, variable names, attributes, operators, comprehensions or f-strings. Such cases are rejected.
- Positional arguments go in "args" in order. Keyword arguments go in "kwargs" as a list of {"name": ..., "value": ...} pairs, with the value written as a literal string like the args.
- For an instance method, also give the constructor arguments of each case in "init_args" and "init_kwargs", written the same way: the instance is built from them, then the method is called. Use values the constructor accepts, so that building the instance succeeds; vary them when the instance's attributes matter to the method.
- Make every case different from the others.
- Give each case a one-sentence "rationale" that says which behavior it targets. Do not predict outputs.
- Reply with JSON only, matching the requested schema.
=== user ===
Function: $function
Signature: $signature
Docstring: $docstring

$task

Class constructor (instance methods only):
$constructor

Old version:
```python
$old_source
```

New version:
```python
$new_source
```

Propose $count cases.
