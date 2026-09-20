; Call sites in Scala, for the heuristic caller/callee graph.
;
; Validated against a real corpus rather than assumed: the 14 .scala files
; in the aoc2025 repo, whose call-site shapes measure as
;
;    242  obj.method(...)     call_expression -> field_expression
;    154  method(...)         call_expression -> identifier
;     15  f(a)(b)             call_expression -> call_expression
;      2  Queue[String]()     call_expression -> generic_function
;      2  new Exception(...)  instance_expression
;
; Curried application needs no pattern of its own - the outer node's
; function *is* the inner call_expression, so matching recurses into it and
; the underlying name is captured once.
;
; Infix calls are deliberately not captured. Scala parses `a + b` and
; `xs to n` both as infix_expression, distinguished only by whether the
; operator is an (operator_identifier) or an (identifier). Capturing the
; named half is possible, but in the corpus it yields exactly `to` (6) and
; `until` (3) - stdlib methods that can never match a symbol defined in one
; of these repos - while the symbolic half is 168 occurrences of `+`, `==`,
; `&&` and friends, which is pure noise. So this stays with the same
; explicit-call-syntax-only rule python_calls.scm and go_calls.scm use.

(call_expression
  function: (identifier) @call_name)

(call_expression
  function: (field_expression
    field: (identifier) @call_name))

(call_expression
  function: (generic_function
    function: (identifier) @call_name))

; `new Foo(...)` is Scala's constructor call, the counterpart of Python's
; `Foo()` - which python_calls.scm already captures as an ordinary call -
; so the constructed type is captured too, letting it resolve to a
; class/trait definition elsewhere in the repo.
(instance_expression
  (type_identifier) @call_name)
