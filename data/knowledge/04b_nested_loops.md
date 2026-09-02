---
subject: python_fundamentals
unit: "4b"
topic: nested loops
skill: nested_loops
difficulty: MEDIUM
prerequisites: [loops]
source: CogniFlow curriculum notes, Unit 4b
license: CC BY-SA 4.0 (original text written for this project)
---

# Unit 4b — Nested Loops

> **Before this unit:** you must be comfortable with Unit 4 (Loops). If a single loop still feels unpredictable, nested loops will multiply that confusion. Go back and trace one loop cleanly before stacking loops together.

## 4b.1 One loop inside another

A nested loop is a loop placed inside another loop. The outer loop controls the larger repetition. For each one of its iterations, the inner loop runs from start to finish.

```python
for row in range(3):
    for col in range(2):
        print(row, col)
```

The output is:

```text
0 0
0 1
1 0
1 1
2 0
2 1
```

The inner loop does not run once total. It runs once for each outer value. Since `row` has three values and `col` has two values for each row, the body runs `3 * 2 = 6` times.

Think of the outer loop as choosing the row of a table. The inner loop walks across the columns in that row. When the inner loop finishes, the outer loop moves to the next row and the inner loop starts again.

## 4b.2 Trace outer and inner values separately

Nested loops become manageable when you track each loop variable separately.

```python
for row in range(2):
    for col in range(3):
        print("cell", row, col)
```

Trace:

| Step | `row` | `col` | Output |
|---:|---:|---:|---|
| 1 | 0 | 0 | `cell 0 0` |
| 2 | 0 | 1 | `cell 0 1` |
| 3 | 0 | 2 | `cell 0 2` |
| 4 | 1 | 0 | `cell 1 0` |
| 5 | 1 | 1 | `cell 1 1` |
| 6 | 1 | 2 | `cell 1 2` |

Notice when `col` resets. It returns to `0` when a new outer iteration starts because `for col in range(3)` begins a fresh inner loop each time.

Wrong mental model:

```text
row changes, col changes, row changes, col changes
```

Right mental model:

```text
for one row, run every column; then move to the next row
```

If you cannot predict this table, the problem is not yet nested loops. It is single-loop tracing from Unit 4.

## 4b.3 Nested loops often describe grids

Rows and columns are the most common beginner use for nested loops.

```python
for row in range(4):
    line = ""
    for col in range(5):
        line = line + "*"
    print(line)
```

This prints four lines, each with five stars.

```text
*****
*****
*****
*****
```

The outer loop decides how many lines. The inner loop decides how many characters per line. The accumulator `line` is reset once per row, before the inner loop starts.

Wrong:

```python
line = ""

for row in range(4):
    for col in range(5):
        line = line + "*"
    print(line)
```

This prints:

```text
*****
**********
***************
********************
```

Because `line` is not reset for each row, it keeps growing across outer iterations.

Right:

```python
for row in range(4):
    line = ""
    for col in range(5):
        line = line + "*"
    print(line)
```

Where you initialise a variable controls how long it remembers information.

## 4b.4 Accumulators belong at the right level

With nested loops, an accumulator may belong to the whole computation or only to one outer iteration. Put it at the level that matches its job.

Suppose you have quiz scores for several students:

```python
scores = [
    [8, 7, 9],
    [6, 10, 8],
]
```

To print each student's total:

```python
for student_scores in scores:
    total = 0
    for score in student_scores:
        total = total + score
    print(total)
```

Here `total` belongs to one student, so it is reset inside the outer loop and before the inner loop.

To compute the class total:

```python
class_total = 0

for student_scores in scores:
    for score in student_scores:
        class_total = class_total + score

print(class_total)
```

Here `class_total` belongs to the whole computation, so it is created before both loops.

Wrong:

```python
class_total = 0

for student_scores in scores:
    class_total = 0
    for score in student_scores:
        class_total = class_total + score

print(class_total)
```

This only prints the total for the last student, because the class total is reset each time the outer loop moves to a new student.

## 4b.5 Avoid using the same loop variable twice

Each loop variable should have its own name. Reusing the same name in an inner loop makes traces confusing and can destroy the outer value.

Wrong:

```python
for i in range(3):
    for i in range(2):
        print(i)
```

Both loops use `i`. The inner loop reassigns `i`, so the name no longer clearly tells you which loop you mean.

Right:

```python
for row in range(3):
    for col in range(2):
        print(row, col)
```

Names such as `row` and `col`, `student` and `score`, or `word` and `letter` show the relationship between the loops. They also make mistakes easier to spot.

This is still a variables issue underneath. A loop variable is a variable assigned by Python. If you reuse the same name, you are reassigning it. Unit 1's rule still applies: one name holds one current value in its scope.

## 4b.6 `break` and `continue` affect the loop they are in

Inside nested loops, `break` exits the nearest loop only. It does not automatically exit every surrounding loop.

```python
for row in range(3):
    for col in range(3):
        if col == 1:
            break
        print(row, col)
```

Output:

```text
0 0
1 0
2 0
```

When `col` becomes `1`, the inner loop stops. Then the outer loop moves to the next `row`, and a fresh inner loop starts.

`continue` also applies to the nearest loop. It skips the rest of the current inner iteration, not the whole outer iteration.

```python
for row in range(2):
    for col in range(3):
        if col == 1:
            continue
        print(row, col)
```

This skips column `1` for each row, but it still prints columns `0` and `2`.

If you need to stop both loops, you usually need a flag variable, a function with `return`, or a different structure. Do not assume one `break` climbs out through every level.

## 4b.7 Diagnosing nested-loop mistakes

When nested-loop output is wrong, reduce the example. Use tiny ranges such as `range(2)` and `range(3)`, then write the table.

Checklist:

| Question | What to inspect |
|---|---|
| How many outer iterations? | the outer sequence or range |
| How many inner iterations per outer iteration? | the inner sequence or range |
| Which variables reset? | assignments before the inner loop |
| Which variables persist? | assignments before the outer loop |
| Which loop does `break` or `continue` affect? | the indentation level |

Example bug:

```python
for row in range(2):
    for col in range(3):
        print(row)
    print(col)
```

The `print(col)` line is outside the inner loop but inside the outer loop. It runs after the inner loop finishes, so it prints the last column value for each row. If you meant to print every cell, indent it inside the inner loop.

Indentation is not decoration in Python. It defines which loop owns a line.

## 4b.8 Common misconceptions

- **"The inner loop continues from where it left off last time."** No. A `for` inner loop starts fresh for each outer iteration. If it says `for col in range(3)`, then `col` becomes `0`, `1`, and `2` for every row.

- **"The body runs `outer + inner` times."** Usually it runs `outer * inner` times. Three rows and two columns produce six cell visits, not five.

- **"All accumulators should be created before all loops."** Only accumulators for the whole computation belong before both loops. Per-row or per-student accumulators must be reset inside the outer loop.

- **"Reusing `i` is harmless because the loops are separate."** It is legal, but it makes the current value hard to reason about and can overwrite the outer loop variable name. Use distinct names that describe the two levels.

- **"A nested-loop bug means I need a clever nested-loop trick."** Usually not. Confusion here is almost always single-loop confusion multiplied. Go back to Unit 4 and trace one loop until you can predict its variable values, then return and add the second loop.

- **"`break` exits every loop I can see."** No. `break` exits the nearest loop. In a nested loop, that is usually the inner loop only.
