---
subject: python_fundamentals
unit: "4"
topic: loops
skill: loops
difficulty: MEDIUM
prerequisites: [conditionals, variables]
source: CogniFlow curriculum notes, Unit 4
license: CC BY-SA 4.0 (original text written for this project)
---

# Unit 4 — Loops

> **Before this unit:** you must be comfortable with Unit 1 (Variables) and Unit 2 (Conditionals). A loop is a conditional that can be checked again and again, so wrong variable updates and wrong conditions become bigger problems here.

## 4.1 Why loops exist

A loop repeats a block of code. Use a loop when the same kind of action must happen many times: checking every item in a list, counting through a range, asking for input until it is valid, or building a total from several values.

Without a loop, repeated code becomes fragile:

```python
total = 0
total = total + scores[0]
total = total + scores[1]
total = total + scores[2]
```

This only works for exactly three scores. A loop describes the pattern instead:

```python
total = 0

for score in scores:
    total = total + score
```

Now the same code works for an empty list, a list with three scores, or a list with one hundred scores. The loop does not care how many items there are; it runs once per item.

The key question is not "How do I repeat this line?" It is "What changes each time?" In the example, `score` changes on each iteration, and `total` changes because it accumulates the scores.

## 4.2 `for` loops visit a known sequence

A `for` loop is best when Python already has a sequence to visit.

```python
names = ["Ada", "Ben", "Chin"]

for name in names:
    print("Hello", name)
```

On each iteration, Python assigns the next item to `name`, then runs the body.

| Iteration | `name` | Output |
|---:|---|---|
| 1 | `"Ada"` | `Hello Ada` |
| 2 | `"Ben"` | `Hello Ben` |
| 3 | `"Chin"` | `Hello Chin` |

The loop variable `name` is just a variable. Python assigns it for you at the start of each iteration. You should not manually change it to move to the next list item.

Wrong:

```python
for name in names:
    print(name)
    name = "done"
```

Changing `name` inside the loop does not change which item Python visits next. On the next iteration, Python assigns the next list value to `name` anyway.

Use a `for` loop when the natural sentence is "for each item in this collection". If you are trying to continue until a condition changes, a `while` loop may express the idea more clearly.

## 4.3 `range` gives controlled counting

`range` creates a sequence of numbers for a `for` loop.

```python
for i in range(5):
    print(i)
```

This prints `0`, `1`, `2`, `3`, and `4`. It does not print `5`. The stop value is excluded.

You can also provide a start and stop:

```python
for i in range(2, 6):
    print(i)
```

This prints `2`, `3`, `4`, and `5`.

Trace `range` before using it in a boundary-sensitive problem:

| Code | Values produced |
|---|---|
| `range(4)` | `0, 1, 2, 3` |
| `range(1, 4)` | `1, 2, 3` |
| `range(1, 5)` | `1, 2, 3, 4` |

If you need to process list indexes, the index values must fit the list. For a list of length `4`, valid indexes are `0`, `1`, `2`, and `3`, so `range(len(items))` is often correct.

```python
for i in range(len(items)):
    print(i, items[i])
```

If your loop is one step short or one step too long, do not guess. Write the first and last values that should run, then choose the `range` that produces exactly those values. This is usually a Unit 2 boundary-condition problem inside a loop.

## 4.4 Accumulators keep results across iterations

Many loops build one answer gradually. The variable that stores the growing answer is called an accumulator.

```python
total = 0

for price in [8, 12, 5]:
    total = total + price

print(total)
```

Trace:

| Iteration | `price` | `total` before | `total` after |
|---:|---:|---:|---:|
| start | - | - | 0 |
| 1 | 8 | 0 | 8 |
| 2 | 12 | 8 | 20 |
| 3 | 5 | 20 | 25 |

The initial value matters. For summing, start with `0`. For multiplying, start with `1`. For collecting strings, start with `""` or a list, depending on the result you need.

Wrong:

```python
for price in [8, 12, 5]:
    total = 0
    total = total + price
```

Here `total` is reset to `0` on every iteration, so it never remembers previous prices.

Right:

```python
total = 0

for price in [8, 12, 5]:
    total = total + price
```

Set up the accumulator before the loop. Update it inside the loop. Use it after the loop.

## 4.5 `while` loops repeat while a condition is true

A `while` loop is best when the number of repetitions is not known in advance.

```python
count = 3

while count > 0:
    print(count)
    count = count - 1

print("done")
```

Before each iteration, Python checks `count > 0`. If it is true, the body runs. If it is false, the loop stops.

| Check | `count` before check | Condition | What happens |
|---:|---:|---|---|
| 1 | 3 | true | print `3`, then set `count` to `2` |
| 2 | 2 | true | print `2`, then set `count` to `1` |
| 3 | 1 | true | print `1`, then set `count` to `0` |
| 4 | 0 | false | exit loop |

A `while` loop needs three parts:

- a variable with an initial value
- a condition that checks that variable
- an update that can eventually make the condition false

If any part is missing, the loop may run the wrong number of times or never stop.

## 4.6 Infinite loops: when the condition never becomes false

An infinite loop happens when the loop condition stays true forever. The usual cause is not that Python is "stuck". The usual cause is that the variables in the condition do not move toward a stopping value.

Wrong:

```python
count = 3

while count > 0:
    print(count)
```

The condition is `count > 0`. The value of `count` starts at `3` and never changes inside the loop. Every check sees `3 > 0`, so the body runs again.

Right:

```python
count = 3

while count > 0:
    print(count)
    count = count - 1
```

Now each iteration moves `count` closer to `0`, where the condition becomes false.

Another wrong version moves the variable in the wrong direction:

```python
count = 3

while count > 0:
    print(count)
    count = count + 1
```

This update makes `count` larger, so `count > 0` remains true. The loop is not missing an update; it has an update that moves away from the stopping condition.

To diagnose an infinite loop, write a three-column trace:

| Iteration | Condition value | Update |
|---:|---|---|
| 1 | `3 > 0` is true | `count` becomes `4` |
| 2 | `4 > 0` is true | `count` becomes `5` |
| 3 | `5 > 0` is true | `count` becomes `6` |

The pattern shows the bug. The condition never becomes false. This is often a Unit 2 conditionals problem: the boundary is wrong, or the update does not make the condition change in the needed direction.

## 4.7 Choosing and tracing loop boundaries

Loops are precise about where they start and stop. A one-step mistake is called an off-by-one error.

Suppose you want to print `1`, `2`, and `3`.

Wrong:

```python
for number in range(1, 3):
    print(number)
```

This prints `1` and `2`, because the stop value `3` is excluded.

Right:

```python
for number in range(1, 4):
    print(number)
```

For `while` loops, the same problem appears in the condition.

Wrong:

```python
number = 1

while number < 3:
    print(number)
    number = number + 1
```

Right:

```python
number = 1

while number <= 3:
    print(number)
    number = number + 1
```

When the loop is one step wrong, do not focus only on the loop keyword. Ask the Unit 2 question: "For the boundary value, should this condition be true or false?" Then test exactly that value.

## 4.8 Common misconceptions

- **"`for i in range(5)` includes `5`."** It does not. `range(5)` produces `0` through `4`. The stop value is excluded.

- **"The loop body decides when a `for` loop moves to the next item."** In a normal `for` loop, Python assigns the next item automatically. Changing the loop variable inside the body does not control the sequence.

- **"An infinite loop is random."** No. An infinite loop has a condition that never becomes false. Find the condition, list the variables it reads, and check whether the loop body changes those variables toward a false condition.

Worked diagnosis:

```python
tries = 0

while tries < 3:
    print("try again")
```

The condition is `tries < 3`. The value starts at `0`. The body never changes `tries`, so every check is `0 < 3`, which is true. Add the update:

```python
tries = 0

while tries < 3:
    print("try again")
    tries = tries + 1
```

- **"If a loop never stops, I should add `break` somewhere."** Sometimes `break` is the right tool, but first fix the loop condition and update. A hidden `break` can hide the fact that the loop's main stopping rule is wrong.

- **"Loop bugs are always loop problems."** Often they are conditionals problems. If the loop stops too early, too late, or never stops, go back to Unit 2 and trace the truth value of the condition at the boundary values. If the names in that condition hold unexpected values, go back again to Unit 1.
