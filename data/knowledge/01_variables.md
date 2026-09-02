---
subject: python_fundamentals
unit: "1"
topic: variables
skill: variables
difficulty: EASY
prerequisites: []
source: CogniFlow curriculum notes, Unit 1
license: CC BY-SA 4.0 (original text written for this project)
---

# Unit 1 — Variables

> **Before this unit:** you do not need earlier Python knowledge. You do need to slow down enough to read code one line at a time. Most variable mistakes come from guessing what a name means instead of checking where it was assigned.

## 1.1 Values and names

A program works with values: numbers, strings, booleans, lists, and many other pieces of data. A variable is a name that refers to a value so you can use that value later.

```python
score = 17
name = "Mina"
passed = True
```

After these three lines, `score` refers to the integer `17`, `name` refers to the string `"Mina"`, and `passed` refers to the boolean value `True`. The variable is not the value itself. It is a label Python can look up.

This distinction matters because Python does not know what a name "should" mean. It only knows names that have actually been assigned in the current place where the code is running. If a line uses `score`, Python searches for a variable called `score`. If it finds one, it reads the value. If it does not, the program stops with an error.

Good variable names make code easier to trace. `total_minutes` tells you more than `x`. However, a good name does not create a value by itself. You still need an assignment before the name can be read.

## 1.2 Assignment happens from right to left

The assignment operator `=` does not mean "is equal to" in the same way it does in algebra. In Python, `=` means: evaluate the expression on the right, then bind the result to the name on the left.

```python
coins = 10
coins = coins + 5
```

The second line is legal because Python first reads the old value of `coins`, computes `10 + 5`, and then stores the new value `15` under the same name. It is not saying that `coins` is mathematically equal to `coins + 5`. It is updating the name.

A common way to trace assignment is to keep a small table:

| Line | Code | Value after the line |
|---|---|---|
| 1 | `coins = 10` | `coins` is `10` |
| 2 | `coins = coins + 5` | `coins` is `15` |

If the right side uses a name, that name must already exist. This version fails:

```python
coins = coins + 5
```

Python cannot add `5` to `coins` because there is no old value of `coins` yet. Before a variable can be updated, it must first be created.

## 1.3 Reading code with a variable table

When a program feels confusing, do not keep the whole thing in your head. Make a variable table and update it after each line. This is especially useful before conditionals, loops, and functions, because those topics all depend on knowing the current values of names.

```python
hours = 2
minutes = hours * 60
hours = hours + 1
total = hours * 60
```

Trace it like this:

| Line | `hours` | `minutes` | `total` |
|---|---:|---:|---:|
| start | undefined | undefined | undefined |
| `hours = 2` | 2 | undefined | undefined |
| `minutes = hours * 60` | 2 | 120 | undefined |
| `hours = hours + 1` | 3 | 120 | undefined |
| `total = hours * 60` | 3 | 120 | 180 |

Notice that `minutes` does not change when `hours` changes later. The line `minutes = hours * 60` computed a value at that moment. It did not create a live formula. If you want `minutes` to reflect the new value of `hours`, you must assign it again.

This is one reason variable traces are more reliable than intuition. Many beginners expect related names to update together because the English words are related. Python does not use the meaning of English words. It follows assignments.

## 1.4 Types decide what operations mean

A variable can refer to different types of values. The type affects what operators do.

```python
age = 19
age_text = "19"

next_age = age + 1       # 20
label = age_text + "!"   # "19!"
```

The `+` operator adds numbers, but joins strings. This version fails:

```python
age_text = "19"
next_age = age_text + 1
```

Python does not guess that `"19"` should become the number `19`. You must convert it:

```python
age_text = "19"
next_age = int(age_text) + 1
```

Types also matter in comparisons. The expression `score > 70` only makes sense if `score` holds a value that can be compared with `70`. Later, in Unit 2, conditionals will depend on expressions like this being true or false. If the name holds an unexpected value, the conditional may appear to be wrong even though the real problem is the variable assignment that came before it.

When you debug, ask two questions about every name in an expression: "Has this name been assigned?" and "What type of value does it currently hold?"

## 1.5 Reassignment and preserving old values

Reassignment replaces what a name refers to. It does not keep a history.

```python
temperature = 18
temperature = 21
```

After the second line, `temperature` is `21`. The old value `18` is gone unless you saved it under another name.

```python
old_temperature = temperature
temperature = 21
change = temperature - old_temperature
```

This pattern appears often: save the old value first, then update the current value. If you overwrite too early, you cannot recover the previous value from the variable.

Wrong:

```python
balance = 100
balance = balance - 30
spent = 100 - balance
```

This works only because the original value `100` is typed again. If the starting balance changes, the calculation may quietly become wrong.

Better:

```python
balance = 100
old_balance = balance
balance = balance - 30
spent = old_balance - balance
```

The better version states the relationship in variables, so the code still works if the starting value changes.

## 1.6 Names inside functions are local

Functions have their own local variables. You will study functions properly in Unit 3, but you need one early warning now: a name created inside a function usually does not exist outside it.

```python
def make_message():
    message = "Ready"
    return message

print(make_message())
print(message)
```

The first `print` works because the function returns the value `"Ready"`. The second `print` fails because `message` was created inside `make_message`. Outside the function, that local name is not available.

This is not a small technical detail. It is one of the main reasons a student sees `NameError` and thinks Python has "forgotten" a variable. Python has not forgotten it. The name was only defined in a different scope.

If you need a value outside a function, return it and assign the result:

```python
def make_message():
    message = "Ready"
    return message

status = make_message()
print(status)
```

Now `status` is a name in the outer part of the program. The local name `message` still belongs only to the function call.

## 1.7 Common misconceptions

- **"If I use a sensible name, Python will know what I mean."** No. A variable name exists only after an assignment has run. `total` is just text until a line such as `total = price + tax` creates it.

- **"`NameError` means Python is broken or the import failed."** Usually it means the name was never defined where you used it. Check spelling first, then check whether the assignment line actually ran before the name was read.

Wrong:

```python
points = 8
print(point)
```

Right:

```python
points = 8
print(points)
```

- **"`NameError` cannot happen if I assigned the name somewhere in the file."** It can. Names have scope. A name defined only inside a function exists only during that function call.

Wrong:

```python
def load_score():
    score = 12

load_score()
print(score)
```

Right:

```python
def load_score():
    score = 12
    return score

score = load_score()
print(score)
```

- **"Changing one variable automatically updates another variable that was calculated from it."** No. Assignment stores the result at that moment. If `minutes = hours * 60` runs when `hours` is `2`, then `minutes` is `120` until you assign it again.

- **"`=` checks whether two things are equal."** In Python, `=` assigns. To compare values, use `==`, which you will use heavily in Unit 2. If conditionals seem strange later, return to Unit 1 and trace what each name actually contains before the comparison runs.
