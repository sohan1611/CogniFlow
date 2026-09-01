---
subject: python_fundamentals
unit: "3"
topic: functions
skill: functions
difficulty: MEDIUM
source: CogniFlow curriculum notes, Unit 3
license: CC BY-SA 4.0 (original text written for this project)
---

# Unit 3 — Functions

## 3.1 What a function actually is

A function is a named, reusable block of code. Defining a function does **not** run it.
Definition and invocation are two separate events, and confusing them is one of the most
common early misunderstandings.

```python
def greet(name):          # definition — nothing executes yet
    return f"Hello, {name}"

message = greet("Asha")   # invocation — the body runs now
```

## 3.2 Parameters versus arguments

- A **parameter** is the name in the definition (`name` above).
- An **argument** is the actual value passed at the call site (`"Asha"`).

When a function is called, each argument is bound to its parameter, and that binding
lives only inside that one call.

## 3.3 return is not print

This distinction causes more confusion than any other topic in this unit.

```python
def double_print(x):
    print(x * 2)          # sends text to the screen, returns None

def double_return(x):
    return x * 2          # hands a VALUE back to the caller

a = double_print(5)       # prints 10, and a is None
b = double_return(5)      # prints nothing, and b is 10
```

`print` is a side effect visible to a human. `return` is a value handed back to the
program. A function with no `return` statement returns `None`.

If you find yourself writing `result = print(...)`, that is the misconception.

## 3.4 The call stack

Every call pushes a **frame** onto the call stack, holding that call's own parameters
and local variables. When the function returns, its frame is popped and its locals are
discarded.

```python
def outer(n):
    return inner(n) + 1

def inner(n):
    return n * 2

outer(5)
```

Execution order:

1. `outer(5)` is called → frame for `outer` pushed, `n = 5`
2. `outer` evaluates `inner(n)` → frame for `inner` pushed, `n = 5`
3. `inner` returns `10` → `inner` frame popped
4. `outer` computes `10 + 1 = 11` → `outer` frame popped
5. The value `11` is handed back to the caller

**A call does not return at the point it was written — it returns after its body
finishes.** The caller waits.

## 3.5 Scope

Names created inside a function are **local** to it and are invisible outside.

```python
def f():
    hidden = 42
    return hidden

f()
print(hidden)   # NameError: 'hidden' is not defined
```

Each call gets a fresh set of locals. Two calls to the same function never share them.

## 3.6 Tracing exercise

Trace this by hand and predict the output before running it:

```python
def add(a, b):
    total = a + b
    return total

def compute(x):
    doubled = add(x, x)
    tripled = add(doubled, x)
    return tripled

print(compute(4))
```

Frame-by-frame:

| Step | Frame | Locals | Returns |
|---|---|---|---|
| 1 | `compute` | `x=4` | — |
| 2 | `add` | `a=4, b=4, total=8` | `8` |
| 3 | `compute` | `x=4, doubled=8` | — |
| 4 | `add` | `a=8, b=4, total=12` | `12` |
| 5 | `compute` | `x=4, doubled=8, tripled=12` | `12` |

Output: `12`

## 3.7 Common misconceptions

- **"`print` and `return` do the same thing."** They do not. Only `return` produces a
  value the surrounding program can use.
- **"The function runs when I define it."** It runs only when called.
- **"Local variables persist between calls."** Each call gets fresh locals.
- **"A function without `return` returns nothing."** It returns `None`, which is a value.
- **"Calling a function inside another function skips back to the top."** No — the
  caller pauses, the callee runs to completion, then the caller resumes.
