---
subject: python_fundamentals
unit: "6"
topic: recursion tree
skill: recursion_tree
difficulty: HARD
prerequisites: [recursion]
source: CogniFlow curriculum notes, Unit 6
license: CC BY-SA 4.0 (original text written for this project)
---

# Unit 6 — Recursion Tree

> **Before this unit:** you must be comfortable with Unit 5 (Recursion). A recursion tree does not fix a broken recursive function. It helps you see the calls that a correct recursive structure creates.

## 6.1 When recursion becomes a tree

In Unit 5, many examples had one recursive call per function call. That creates a chain: one call waits for one smaller call, which waits for one smaller call, and so on.

Some recursive functions make more than one recursive call. That creates a tree. Each call becomes a node, and each recursive call it makes becomes a child node.

```python
def count_nodes(n):
    if n <= 1:
        return 1
    left = count_nodes(n - 1)
    right = count_nodes(n - 2)
    return 1 + left + right
```

For `count_nodes(4)`, the first call makes two more calls: `count_nodes(3)` and `count_nodes(2)`. The call to `count_nodes(3)` also makes two calls. The shape branches.

```text
count_nodes(4)
├── count_nodes(3)
│   ├── count_nodes(2)
│   └── count_nodes(1)
└── count_nodes(2)
```

The tree is not the same thing as the final answer. It is a map of the work the program does. You still need to understand what each call returns and how the parent combines those returns.

## 6.2 Each node is a complete function call

Every node in a recursion tree is a full call with its own parameter values and local variables. Do not treat a node as only a number or only a branch label.

```python
def ways(n):
    if n == 0:
        return 1
    if n < 0:
        return 0
    return ways(n - 1) + ways(n - 2)
```

The tree for `ways(3)` starts like this:

```text
ways(3)
├── ways(2)
│   ├── ways(1)
│   └── ways(0)
└── ways(1)
    ├── ways(0)
    └── ways(-1)
```

Each node runs the same function body. For `ways(0)`, the first base case returns `1`. For `ways(-1)`, the second base case returns `0`. For `ways(2)`, neither base case applies, so it branches again.

Trace a node like a normal function call:

| Node | `n` | Base case? | Children | Return |
|---|---:|---|---|---:|
| `ways(0)` | 0 | yes | none | 1 |
| `ways(-1)` | -1 | yes | none | 0 |
| `ways(1)` | 1 | no | `ways(0)`, `ways(-1)` | 1 |

The tree gives structure. The frame trace gives values.

## 6.3 Base cases are the leaves

The leaves of a recursion tree are the calls that do not make more recursive calls. In a correct recursive function, these are the base cases.

```python
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)
```

For `fib(4)`, the leaves are calls such as `fib(1)` and `fib(0)`.

```text
fib(4)
├── fib(3)
│   ├── fib(2)
│   │   ├── fib(1)
│   │   └── fib(0)
│   └── fib(1)
└── fib(2)
    ├── fib(1)
    └── fib(0)
```

The base case `n <= 1` is what stops the tree from growing forever. If the base case is missing, too narrow, or unreachable, the tree does not have proper leaves. It keeps expanding until Python reaches its recursion limit.

Wrong:

```python
def fib(n):
    if n == 1:
        return 1
    return fib(n - 1) + fib(n - 2)
```

This fails for `fib(0)` because `0` is not handled. It calls `fib(-1)` and `fib(-2)`, moving away from a useful stop.

Right:

```python
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)
```

If your tree has no leaves for some input, return to Unit 5. That is a recursion base-case problem before it is a recursion-tree problem.

## 6.4 Returns flow upward from the leaves

Python does not compute a parent node's return until its child calls have returned. The values flow upward.

Using `fib(4)`:

| Node | Child returns | Node return |
|---|---|---:|
| `fib(1)` | base case | 1 |
| `fib(0)` | base case | 0 |
| `fib(2)` | `fib(1) = 1`, `fib(0) = 0` | 1 |
| `fib(3)` | `fib(2) = 1`, `fib(1) = 1` | 2 |
| `fib(4)` | `fib(3) = 2`, `fib(2) = 1` | 3 |

The parent call waits at this line:

```python
return fib(n - 1) + fib(n - 2)
```

It cannot add the two values until both recursive calls have returned. If you only trace downward, you see calls being created but not answers being assembled. A complete recursion-tree trace has two passes:

1. expand downward until base cases
2. compute returns upward from the leaves

This upward pass is where many mistakes become visible. If one child returns `None`, the parent cannot combine it with a number. If one branch is missing, the parent has less information than the formula expects.

## 6.5 Combining child results is the main job

In branching recursion, the parent usually combines child results. The combine step must match the question.

Suppose you want the number of ways to climb `n` stairs if each move is 1 or 2 stairs:

```python
def climb(n):
    if n == 0:
        return 1
    if n < 0:
        return 0
    one_step = climb(n - 1)
    two_steps = climb(n - 2)
    return one_step + two_steps
```

The two child calls answer two different subquestions:

| Child call | Meaning |
|---|---|
| `climb(n - 1)` | ways after taking a 1-step move |
| `climb(n - 2)` | ways after taking a 2-step move |

Because the choices are alternatives, the parent adds the counts.

Wrong:

```python
def climb(n):
    if n == 0:
        return 1
    if n < 0:
        return 0
    climb(n - 1)
    climb(n - 2)
```

This creates a tree, but it throws away the child returns. The function returns `None`, not the number of ways.

Right:

```python
def climb(n):
    if n == 0:
        return 1
    if n < 0:
        return 0
    return climb(n - 1) + climb(n - 2)
```

If your tree shape is correct but the answer is wrong, inspect the combine line. The children may be right, while the parent is adding, multiplying, comparing, or returning the wrong thing.

## 6.6 Repeated subtrees are still real calls

A recursion tree can contain repeated calls with the same argument. In `fib(4)`, `fib(2)` appears twice if you expand larger inputs. Those are separate calls unless the program uses caching.

```text
fib(5)
├── fib(4)
│   ├── fib(3)
│   └── fib(2)
└── fib(3)
    ├── fib(2)
    └── fib(1)
```

The two `fib(3)` nodes are not shared in the simple recursive version. Python computes each call separately. This is why some branching recursive functions become slow quickly: the tree grows faster than the input number.

For learning recursion trees, do not skip repeated nodes too early. Draw them at first so you can see the actual work. Later, you can learn memoisation, where the program remembers previous results. Memoisation changes performance, but it does not change the meaning of the recurrence.

The important point for now is correctness: repeated subtrees still follow the same base-case and return rules. If one repeated subtree has a broken base case, every copy has the same problem.

## 6.7 Diagnosing a broken recursion tree

When a recursion-tree problem fails, separate the bug into one of three layers.

First, check the base cases. Are there leaves for every path? Try small inputs such as `0`, `1`, and `2`. If a path keeps moving into negative numbers or larger numbers, the base case or the movement toward it is wrong.

Second, check the recursive calls. Do they represent smaller versions of the original problem? For `climb(n)`, `climb(n - 1)` and `climb(n - 2)` are smaller stair problems. A call such as `climb(n + 1)` moves away from the base cases.

Third, check the combine step. Once the children return correct answers, does the parent use those answers correctly?

Wrong combine:

```python
def leaves(n):
    if n == 0:
        return 1
    left = leaves(n - 1)
    right = leaves(n - 1)
    return left
```

The tree has two children, but the parent ignores `right`.

Right:

```python
def leaves(n):
    if n == 0:
        return 1
    left = leaves(n - 1)
    right = leaves(n - 1)
    return left + right
```

If the base case or a missing `return` is wrong, go back to Unit 5 before trying to draw a larger tree. A broken tree usually means the recursive function itself is broken.

## 6.8 Common misconceptions

- **"A recursion tree is the order Python runs calls."** Not exactly. The tree shows parent-child relationships between calls. Python still follows a call stack, usually exploring one branch before returning to the parent and then visiting the next branch.

- **"Only one branch matters because the first recursive call runs first."** No. If the function combines two child returns, both branches matter. The first call may run first, but the parent still waits for the second call before it can return.

- **"Repeated nodes with the same argument are the same call."** In plain recursion, they are separate calls. They have the same input and return the same value, but Python computes each one unless caching is added.

- **"If the drawn tree looks large, the code must be wrong."** Not always. Some correct recursive definitions naturally create large trees. Size is a performance concern; missing leaves or missing returns are correctness concerns.

- **"A recursion-tree mistake can be fixed by drawing more levels."** Drawing more levels will not fix a faulty base case or a discarded return. If leaves never appear, or child values do not flow back to the parent, return to Unit 5 and repair the recursive function before expanding the tree further.
