---
subject: python_fundamentals
unit: "5"
topic: recursion
skill: recursion
difficulty: HARD
prerequisites: [functions, conditionals]
source: CogniFlow curriculum notes, Unit 5
license: CC BY-SA 4.0 (original text written for this project)
---

# Unit 5 — Recursion

> **Before this unit:** you must be comfortable with Unit 3 (Functions), especially the
> call stack and the difference between `return` and `print`. Nearly every recursion
> failure is really a function-call failure wearing a costume.

## 5.1 The idea

A recursive function calls itself on a smaller version of the same problem. Every
correct recursive function has two parts:

1. A **base case** — an input small enough to answer directly, without recursing.
2. A **recursive case** — reduces the problem and calls itself.

```python
def factorial(n):
    if n <= 1:          # base case
        return 1
    return n * factorial(n - 1)   # recursive case
```

## 5.2 Why the base case is not optional

Without a base case, the function calls itself forever until Python gives up:

```python
def broken(n):
    return n * broken(n - 1)   # never stops

broken(5)   # RecursionError: maximum recursion depth exceeded
```

A `RecursionError` almost always means one of:

- there is no base case at all,
- the base case exists but is unreachable (the argument never reaches it),
- the recursive call does not actually shrink the problem.

## 5.3 Tracing the stack

`factorial(4)` builds a stack four frames deep before anything returns:

```
factorial(4) → 4 * factorial(3)
                   factorial(3) → 3 * factorial(2)
                                      factorial(2) → 2 * factorial(1)
                                                         factorial(1) → 1     [base]
                                      factorial(2) = 2 * 1  = 2
                   factorial(3) = 3 * 2  = 6
factorial(4) = 4 * 6  = 24
```

Note the shape: the calls all go **down** first, and the values come back **up**
afterwards. Nothing is computed on the way down except the next call.

## 5.4 The most common recursion bug

Forgetting to `return` the recursive call:

```python
def bad_sum(n):
    if n == 0:
        return 0
    bad_sum(n - 1) + n     # computed, then thrown away — returns None

def good_sum(n):
    if n == 0:
        return 0
    return good_sum(n - 1) + n
```

`bad_sum` returns `None`, and the caller then fails with
`TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'`.

**This is a `return` misunderstanding, not a recursion misunderstanding.** If this bug
keeps appearing, the real gap is Unit 3, not Unit 5 — go back and re-trace the call
stack there before continuing here.

## 5.5 Worked example — sum of a list

```python
def total(items):
    if not items:           # base case: empty list
        return 0
    return items[0] + total(items[1:])
```

`total([1, 2, 3])` → `1 + total([2, 3])` → `1 + (2 + total([3]))`
→ `1 + (2 + (3 + total([])))` → `1 + (2 + (3 + 0))` → `6`

## 5.6 Practice

1. Write `count_down(n)` printing `n` down to `1`, then `"done"`.
2. Write `reverse(s)` returning a reversed string recursively.
3. Write `fib(n)` for the nth Fibonacci number. Trace `fib(4)` by hand and count how
   many calls happen — this motivates memoisation later.

## 5.7 Common misconceptions

- **"The recursive call returns to the top of the function."** No — it starts a new
  frame with its own locals, and the current frame waits.
- **"I don't need `return` in front of the recursive call."** You almost always do.
- **"Recursion is a loop."** It builds a stack of pending frames; a loop does not.
- **"The base case goes at the end."** It must be checked *before* recursing, or it is
  never reached.
