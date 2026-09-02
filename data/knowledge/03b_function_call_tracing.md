---
subject: python_fundamentals
unit: "3b"
topic: function call tracing
skill: function_call_tracing
difficulty: MEDIUM
prerequisites: [functions]
source: CogniFlow curriculum notes, Unit 3b
license: CC BY-SA 4.0 (original text written for this project)
---

# Unit 3b — Function Call Tracing

> **Before this unit:** you must know Unit 3 (Functions): parameters, arguments, local variables, `return`, and the difference between defining a function and calling it. This unit is deliberate practice for when those ideas still break during real code.

## 3b.1 Why tracing function calls matters

A function call pauses the current line, runs another block of code, and then comes back with a return value. Many function bugs happen because the programmer imagines the call as a single word, not as a sequence of steps.

```python
def add_tax(price):
    tax = price * 0.1
    return price + tax

total = add_tax(20)
print(total)
```

The line `total = add_tax(20)` is not one simple action. It contains a call. Python must:

1. remember where to come back
2. create a new function frame
3. bind `price` to `20`
4. run the function body
5. return a value
6. assign that value to `total`

When you trace calls this way, `return` stops feeling like magic. It is the value sent back to the paused caller.

This unit is the remediation target for function misunderstandings. If you keep losing return values, mixing up parameters and arguments, or expecting local variables to exist outside the function, trace frames here before moving on.

## 3b.2 A frame is one running call

Each function call gets its own frame. A frame contains that call's local variables. If the same function is called twice, those are two separate frames, even if the parameter names are the same.

```python
def double(x):
    result = x * 2
    return result

a = double(3)
b = double(5)
```

Trace:

| Step | Frame | Locals | Return |
|---:|---|---|---|
| 1 | global | `a` undefined, `b` undefined | - |
| 2 | `double(3)` | `x = 3`, `result = 6` | `6` |
| 3 | global | `a = 6`, `b` undefined | - |
| 4 | `double(5)` | `x = 5`, `result = 10` | `10` |
| 5 | global | `a = 6`, `b = 10` | - |

The local name `result` appears in both calls, but it is not shared. The first call's `result` is `6`; the second call's `result` is `10`. When a call finishes, its frame is gone. Only the returned value remains available to the caller.

## 3b.3 Trace the caller and callee separately

The caller is the code that makes the function call. The callee is the function being called. A clean trace keeps them separate.

```python
def make_label(name, score):
    label = name + ": " + str(score)
    return label

message = make_label("Ravi", 9)
print(message)
```

Trace the caller first:

| Caller step | Code | What happens |
|---:|---|---|
| 1 | `message = make_label("Ravi", 9)` | call `make_label`; assignment waits |
| 2 | `print(message)` | cannot run until the call returns |

Now trace the callee:

| Callee frame | Locals after binding | Return value |
|---|---|---|
| `make_label("Ravi", 9)` | `name = "Ravi"`, `score = 9`, `label = "Ravi: 9"` | `"Ravi: 9"` |

Now return to the caller:

| Caller step | Code | Result |
|---:|---|---|
| 1 resumes | `message = make_label("Ravi", 9)` | `message = "Ravi: 9"` |
| 2 | `print(message)` | prints `Ravi: 9` |

This two-part trace prevents a common mistake: assigning local variables from the function directly into the caller. The caller receives only the return value.

## 3b.4 Predict output before running it

To build reliable skill, practise predicting output before running code. You are not guessing; you are simulating Python's steps.

```python
def shout(word):
    print("inside", word)
    return word.upper()

answer = shout("go")
print("outside", answer)
```

Trace:

| Step | Frame | Action |
|---:|---|---|
| 1 | global | call `shout("go")`; assignment to `answer` waits |
| 2 | `shout` | `word = "go"` |
| 3 | `shout` | prints `inside go` |
| 4 | `shout` | returns `"GO"` |
| 5 | global | `answer = "GO"` |
| 6 | global | prints `outside GO` |

Output:

```text
inside go
outside GO
```

The print inside the function happens before the print after the call because the caller is paused during the call. This ordering matters when tests compare exact output.

Try the same method with this example:

```python
def f(x):
    print(x)
    return x + 1

def g(y):
    value = f(y * 2)
    print(value)
    return value + 3

print(g(4))
```

Do not run it first. Make a frame table, then compare your prediction with the interpreter. The goal is to make your mental model strict enough that surprises become visible.

## 3b.5 Nested calls return from the inside out

Function calls can be nested inside expressions. Python must evaluate the inner call before the outer expression can finish.

```python
def add_one(n):
    return n + 1

def square(n):
    return n * n

result = square(add_one(4))
```

Trace:

| Step | Waiting expression | Active call | Return |
|---:|---|---|---|
| 1 | `square(add_one(4))` | `add_one(4)` | `5` |
| 2 | `square(5)` | `square(5)` | `25` |
| 3 | `result = 25` | none | - |

The outer call `square(...)` cannot start fully until its argument value is known. The argument is `add_one(4)`, so that call runs first.

Wrong mental model:

```text
square starts, then add_one happens somewhere inside square
```

Right mental model:

```text
add_one(4) returns 5, then square(5) starts
```

This is the same idea you will need for recursion later. A call can wait for another call to return. The caller does not disappear; it is paused.

## 3b.6 Returning a value is different from printing it

Printing displays text to the console. Returning sends a value back to the caller. A function can do either, both, or neither, but they are not interchangeable.

Wrong:

```python
def add(a, b):
    print(a + b)

total = add(2, 3)
print(total * 10)
```

The function prints `5`, but it does not return `5`. In Python, a function with no explicit `return` returns `None`, so `total` becomes `None`. Multiplying `None` by `10` fails.

Right:

```python
def add(a, b):
    return a + b

total = add(2, 3)
print(total * 10)
```

Trace:

| Step | Frame | Action |
|---:|---|---|
| 1 | global | call `add(2, 3)` |
| 2 | `add` | `a = 2`, `b = 3` |
| 3 | `add` | return `5` |
| 4 | global | `total = 5` |
| 5 | global | print `50` |

When you need to use the result in another calculation, return it. Print only when the goal is output for a human reader.

## 3b.7 Drill: make the invisible stack visible

For each call, write one row with the frame name, the local variables, and the return value. Leave the return column blank until the function reaches a `return`.

Example:

```python
def discount(price):
    return price - 2

def final_price(price):
    after_discount = discount(price)
    return after_discount + 1

cost = final_price(10)
```

Frame table:

| Frame | Locals | Waiting for | Returns |
|---|---|---|---|
| global | `cost` waiting | `final_price(10)` | - |
| `final_price(10)` | `price = 10` | `discount(price)` | - |
| `discount(10)` | `price = 10` | nothing | `8` |
| `final_price(10)` | `after_discount = 8` | nothing | `9` |
| global | `cost = 9` | nothing | - |

A good tracing habit is mechanical:

1. Circle each call.
2. Draw a frame for the active call.
3. Bind parameters to argument values.
4. Run lines in order.
5. Write the returned value at the call site.

If you cannot say where a return value goes, that is the bug to fix.

## 3b.8 Common misconceptions

- **"The function definition runs when Python reads it."** No. `def` creates the function. The body runs only when the function is called.

- **"Arguments and parameters are the same thing."** They are connected, but not identical. Arguments are the values at the call site. Parameters are the local names inside the function frame.

- **"A local variable is available after the function finishes."** No. The caller gets the return value, not the callee's local names.

- **"Printing a value returns it."** No. Printing displays a value. Returning passes a value back to the caller. If later code needs the value, use `return`.

- **"A nested call runs from left to right without pausing."** A call inside another expression must return before the outer expression can finish. Trace inside out.

- **"I understand functions because I can write one, so tracing is optional."** When function failures repeat, tracing is the repair skill. Use a frame table until you can predict the output before running the program.
