---
subject: python_fundamentals
unit: "2"
topic: conditionals
skill: conditionals
difficulty: EASY
prerequisites: [variables]
source: CogniFlow curriculum notes, Unit 2
license: CC BY-SA 4.0 (original text written for this project)
---

# Unit 2 — Conditionals

> **Before this unit:** you must be comfortable with Unit 1 (Variables). A conditional can only make a good decision if the names in the condition hold the values you think they hold.

## 2.1 A conditional chooses which path runs

A conditional lets a program choose between paths. Python evaluates a condition, gets either `True` or `False`, and then runs the matching block.

```python
score = 82

if score >= 70:
    print("pass")
else:
    print("try again")
```

The condition is `score >= 70`. Because `score` is `82`, the condition is true, so Python prints `"pass"` and skips the `else` block.

The important habit is to separate the decision from the action. First ask, "What value does this condition produce?" Only after that ask, "Which block runs?" If you mix those two questions together, it is easy to guess from the story of the program instead of tracing the actual values.

| Step | Question | Answer |
|---|---|---|
| 1 | What is `score`? | `82` |
| 2 | What is `score >= 70`? | `True` |
| 3 | Which block runs? | the `if` block |

Conditionals do not repeat by themselves. An `if` statement checks once when execution reaches it. Loops and recursion can cause a condition to be checked many times, but the conditional itself is still a single decision each time it is reached.

## 2.2 Boolean expressions are ordinary values

The result of a comparison is a boolean value: `True` or `False`.

```python
age = 16
can_drive = age >= 17
print(can_drive)
```

This prints `False`. The variable `can_drive` holds a boolean just as `age` holds a number.

You can combine boolean expressions with `and`, `or`, and `not`.

```python
has_ticket = True
age = 15

if has_ticket and age >= 12:
    print("enter")
```

For `and`, both sides must be true. For `or`, at least one side must be true. `not` reverses a boolean.

Do not read these words too loosely. Python follows exact rules:

| Expression | Result |
|---|---|
| `True and False` | `False` |
| `True or False` | `True` |
| `not True` | `False` |
| `not False` | `True` |

When a combined condition surprises you, write down the result of each smaller comparison first. Do not try to evaluate the whole line in one leap.

## 2.3 `if`, `elif`, and `else` form one decision chain

An `if` / `elif` / `else` chain chooses the first true branch and skips the rest.

```python
mark = 74

if mark >= 90:
    grade = "A"
elif mark >= 70:
    grade = "B"
elif mark >= 50:
    grade = "C"
else:
    grade = "D"
```

Here, `mark >= 90` is false. Then `mark >= 70` is true, so `grade` becomes `"B"`. Python does not also check whether `mark >= 50` should run. The chain has already chosen a path.

Order matters. This version is wrong:

```python
mark = 74

if mark >= 50:
    grade = "C"
elif mark >= 70:
    grade = "B"
```

The first condition is already true, so the `elif` is never reached. The code gives `"C"` even though the student should receive `"B"`.

The rule is: put the most specific or highest-priority conditions first. If one condition includes another, the narrower condition usually needs to come earlier.

## 2.4 Conditions depend on the variables behind them

When a conditional behaves strangely, the condition is often not the real source of the bug. The real source is a variable holding an unexpected value. That is a Unit 1 problem wearing a Unit 2 costume.

Wrong:

```python
score = "82"

if score >= 70:
    print("pass")
```

The programmer meant `score` to be a number, but it is a string. The comparison with `70` is not the decision you think it is. Fix the value before blaming the conditional:

```python
score = int("82")

if score >= 70:
    print("pass")
```

Truthiness can also hide variable mistakes. Some values act as false in a condition: `False`, `None`, `0`, `""`, and empty containers such as `[]`. Many other values act as true.

```python
name = ""

if name:
    print("Hello", name)
else:
    print("Name missing")
```

This prints `"Name missing"` because the empty string is falsey. If you expected the first branch, go back to Unit 1 and trace where `name` was assigned. Conditionals cannot repair a wrong value; they can only respond to the value they receive.

## 2.5 Conditions must match the boundary you mean

Many bugs happen at the exact boundary between two cases. Should the threshold be included or excluded? Should the final item count? Should zero be allowed?

Compare these:

```python
if age > 18:
    print("adult")
```

```python
if age >= 18:
    print("adult")
```

The first version excludes someone who is exactly `18`. The second includes them. Neither operator is always right. The right one is the one that matches the rule.

Write boundary examples before writing the code:

| Rule | Test value | Expected result |
|---|---:|---|
| adult starts at 18 | 17 | not adult |
| adult starts at 18 | 18 | adult |
| adult starts at 18 | 19 | adult |

Then choose the comparison that makes those examples true.

Boundary thinking will return in Unit 4 when loops stop one step too early or one step too late. In many loop bugs, the loop is not mysterious. The stopping condition simply does not match the boundary case.

## 2.6 A condition that never becomes true means code never stops

Some conditionals are used as stopping rules. In recursion, the stopping rule is called a base case. In loops, the stopping rule is usually the condition becoming false. Either way, the idea is the same: some condition must eventually be satisfied so the repeated work can stop.

Wrong recursive shape:

```python
def count_down(n):
    if n == 0:
        return "done"
    return count_down(n + 1)
```

The base case says "stop when `n` is `0`", but the recursive call moves from `n` to `n + 1`. If the function starts at `3`, the values are `3`, `4`, `5`, `6`, and so on. The condition `n == 0` never becomes true, so the code does not terminate normally.

Right:

```python
def count_down(n):
    if n == 0:
        return "done"
    return count_down(n - 1)
```

Now the values move toward the condition:

| Call | `n` | Is `n == 0` true? |
|---|---:|---|
| 1 | 3 | no |
| 2 | 2 | no |
| 3 | 1 | no |
| 4 | 0 | yes |

If code never stops, ask: "What condition is supposed to end it?" and "Which assignment or call moves the values closer to that condition?" If nothing moves toward the condition, the problem is not speed. The stopping condition is unreachable.

## 2.7 Trace conditionals before changing them

When you are stuck, resist the urge to swap operators at random. Trace the condition for a few concrete inputs.

```python
def shipping_cost(items):
    if items == 0:
        return 0
    elif items < 3:
        return 5
    else:
        return 10
```

Trace:

| `items` | `items == 0` | `items < 3` | Return |
|---:|---|---|---:|
| 0 | true | not checked | 0 |
| 1 | false | true | 5 |
| 2 | false | true | 5 |
| 3 | false | false | 10 |

This table tells you whether the code matches the intended rule. If the table is wrong, change the condition that fails the example. If the table is right but the program still fails, look outside the conditional: the caller may be passing the wrong value, or a variable may have been assigned incorrectly earlier.

Tracing turns a vague complaint like "the if statement is broken" into a specific claim: "when `items` is `3`, the second condition should be false, and it is." That kind of claim can be tested and fixed.

## 2.8 Common misconceptions

- **"`else` means the previous condition was almost true."** No. `else` means none of the earlier branches in the chain ran. It does not tell you how close any comparison was.

- **"Changing `>` to `>=` is a harmless fix."** It changes the boundary. Use example values on both sides of the threshold before changing an operator.

- **"A condition checks continuously."** No. An `if` statement checks when execution reaches it. If a variable changes later, the earlier `if` decision is not revised.

- **"If a base case exists, recursion will stop."** Not necessarily. The base case condition must eventually become true. This is the detected `missing_base_case` shape: the code may contain an `if`, but if the changing value moves away from it or skips over it, the stop condition is never satisfied and the program keeps calling or looping until it fails.

Wrong:

```python
def reach_zero(n):
    if n == 0:
        return 0
    return reach_zero(n + 2)
```

Right for positive `n`:

```python
def reach_zero(n):
    if n == 0:
        return 0
    return reach_zero(n - 1)
```

- **"The conditional is wrong because the branch surprised me."** Maybe, but first check the variables. If `score` is `"82"` instead of `82`, or `name` is `""` instead of `"Asha"`, the condition is responding correctly to the wrong value. That is Unit 1 material: trace the assignment before rewriting the branch.
