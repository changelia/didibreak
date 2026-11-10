# Owner spot check: 10 unexpected findings (task 21a re-run)

Prepared in task 22 for the owner's own review of the labels. The owner reads
the sources, inputs and outcomes below and compares them with the labels.

## How the sample was drawn

- Population: all **193** `unexpected` findings in `rerun-21a/reports/`
  (report files in name order, findings in report order).
- `random.Random(22).shuffle(findings)`, first 10. Same method as the
  independent check (seed 21, 60 findings), different seed.
- Sources are read from the evaluation clones with `git show`. For a
  **replay** the base (*old*) is the bug-fix commit and the checked tree
  (*new*) is its parent, so *new* is the version with the bug. For a
  **seeded** scenario *new* is the base plus the patch in `patches/`.

## Result

| # | Function | Call | Saved label | Independent (seed 21) | This check |
| --- | --- | --- | --- | --- | --- |
| 1 | `sqlparse/utils.py::remove_quotes` | `remove_quotes([{}, {}])` | not real | not sampled | not real |
| 2 | `more_itertools/more.py::nth_combination_with_replacement` | `nth_combination_with_replacement([7], 2, 0)` | real | not sampled | real |
| 3 | `src/humanize/number.py::metric` | `metric(9.9999, 's', 4)` | real | not sampled | real |
| 4 | `more_itertools/more.py::exactly_n` | `exactly_n([0], 9223372036854775807)` | real | real | real |
| 5 | `more_itertools/more.py::nth_permutation` | `nth_permutation({'red', 'blue'}, 3, 0)` | real | real | real |
| 6 | `more_itertools/more.py::nth_permutation` | `nth_permutation('a', 2, 0)` | real | not sampled | real |
| 7 | `src/validators/card.py::mastercard` | `mastercard('2722000000000003')` | real | not sampled | real |
| 8 | `src/packaging/licenses/__init__.py::canonicalize_license_expression` | `canonicalize_license_expression('(LicenseRef-Echo OR lice...` | real | not sampled | real |
| 9 | `more_itertools/more.py::nth_combination_with_replacement` | `nth_combination_with_replacement([1, 2], 3, 0)` | real | real | real |
| 10 | `boltons/strutils.py::singularize` | `singularize('fuss')` | real | not sampled | real |

This check agrees with the saved labels on **10 of 10** (9 real, 1 not real).
Three items (4, 5, 9) were also in the seed 21 sample and all three labellers
agree on them. Items 4, 5 and 6 are borderline (a huge `int`, and an exception
type change on an input both versions reject); they are the ones worth the
owner's own look. All labels here come from models applying the written
rubric in `README.md`; none is a human label.

## 1. `sqlparse/utils.py::remove_quotes`

- Scenario: `sqlparse-seeded-refactor-remove_quotes` (seeded), repository `sqlparse`, commit `09dbe1eec31e`
- Finding id: `756ef1cd57f1`
- Intent: Refactor remove_quotes() for readability; behavior must not change.
- Inputs: `[{}, {}]`
- Before (old): return `builtins.list`, `[{}, {}]`
- After (new): exception `builtins.TypeError`, `TypeError("'in <string>' requires string as left operand, not dict")`
- Saved label: not real (out of contract: bytes, list or tuple; the function is documented for strings (unannotated, so not filtered))
- **This check: not real.** Out of contract. `remove_quotes` is documented as a helper for strings; a list of dicts is not a string. The parameter is unannotated, so the task 21a type filter cannot drop it.

Changed lines:

```diff
--- old
+++ new
@@ -2,6 +2,7 @@
     """Helper that removes surrounding quotes from strings."""
     if val is None:
-        return
-    if val[0] in ('"', "'", '`') and val[0] == val[-1]:
-        val = val[1:-1]
+        return None
+    quote = val[0]
+    if quote in '"\'`' and val[-1] == quote:
+        return val[1:-1]
     return val
```

<details><summary>Full old source</summary>

```python
def remove_quotes(val):
    """Helper that removes surrounding quotes from strings."""
    if val is None:
        return
    if val[0] in ('"', "'", '`') and val[0] == val[-1]:
        val = val[1:-1]
    return val
```

</details>

<details><summary>Full new source</summary>

```python
def remove_quotes(val):
    """Helper that removes surrounding quotes from strings."""
    if val is None:
        return None
    quote = val[0]
    if quote in '"\'`' and val[-1] == quote:
        return val[1:-1]
    return val
```

</details>

## 2. `more_itertools/more.py::nth_combination_with_replacement`

- Scenario: `more-itertools-replay-06f3181` (replay), repository `more-itertools`, commit `06f31819121e`
- Finding id: `e4fee7393715`
- Intent: Refactor the more module for readability; behavior must not change.
- Inputs: `[7], 2, 0`
- Before (old): return `builtins.tuple`, `(7, 7)`
- After (new): exception `builtins.ValueError`, `ValueError()`
- Saved label: real (reverted bug fix: in-contract behavior change the intent forbids)
- **This check: real.** Combinations with replacement allow `r` larger than the pool: `(7, 7)` is the correct second-order combination of `[7]`. The new code raises `ValueError` for a valid call.

Changed lines:

```diff
--- old
+++ new
@@ -12,16 +12,19 @@
         (0, 1, 1)
 
-    ``ValueError`` will be raised If *r* is negative.
+    ``ValueError`` will be raised If *r* is negative or greater than the length
+    of *iterable*.
     ``IndexError`` will be raised if the given *index* is invalid.
     """
     pool = tuple(iterable)
     n = len(pool)
-    if r < 0:
+    if (r < 0) or (r > n):
         raise ValueError
-    c = comb(n + r - 1, r) if n else 0 if r else 1
+
+    c = comb(n + r - 1, r)
 
     if index < 0:
         index += c
-    if not 0 <= index < c:
+
+    if (index < 0) or (index >= c):
         raise IndexError
 
```

<details><summary>Full old source</summary>

```python
def nth_combination_with_replacement(iterable, r, index):
    """Equivalent to
    ``list(combinations_with_replacement(iterable, r))[index]``.


    The subsequences with repetition of *iterable* that are of length *r* can
    be ordered lexicographically. :func:`nth_combination_with_replacement`
    computes the subsequence at sort position *index* directly, without
    computing the previous subsequences with replacement.

        >>> nth_combination_with_replacement(range(5), 3, 5)
        (0, 1, 1)

    ``ValueError`` will be raised If *r* is negative.
    ``IndexError`` will be raised if the given *index* is invalid.
    """
    pool = tuple(iterable)
    n = len(pool)
    if r < 0:
        raise ValueError
    c = comb(n + r - 1, r) if n else 0 if r else 1

    if index < 0:
        index += c
    if not 0 <= index < c:
        raise IndexError

    result = []
    i = 0
    while r:
        r -= 1
        while n >= 0:
            num_combs = comb(n + r - 1, r)
            if index < num_combs:
                break
            n -= 1
            i += 1
            index -= num_combs
        result.append(pool[i])

    return tuple(result)
```

</details>

<details><summary>Full new source</summary>

```python
def nth_combination_with_replacement(iterable, r, index):
    """Equivalent to
    ``list(combinations_with_replacement(iterable, r))[index]``.


    The subsequences with repetition of *iterable* that are of length *r* can
    be ordered lexicographically. :func:`nth_combination_with_replacement`
    computes the subsequence at sort position *index* directly, without
    computing the previous subsequences with replacement.

        >>> nth_combination_with_replacement(range(5), 3, 5)
        (0, 1, 1)

    ``ValueError`` will be raised If *r* is negative or greater than the length
    of *iterable*.
    ``IndexError`` will be raised if the given *index* is invalid.
    """
    pool = tuple(iterable)
    n = len(pool)
    if (r < 0) or (r > n):
        raise ValueError

    c = comb(n + r - 1, r)

    if index < 0:
        index += c

    if (index < 0) or (index >= c):
        raise IndexError

    result = []
    i = 0
    while r:
        r -= 1
        while n >= 0:
            num_combs = comb(n + r - 1, r)
            if index < num_combs:
                break
            n -= 1
            i += 1
            index -= num_combs
        result.append(pool[i])

    return tuple(result)
```

</details>

## 3. `src/humanize/number.py::metric`

- Scenario: `humanize-replay-e46732e` (replay), repository `humanize`, commit `e46732ed2350`
- Finding id: `a6a47c034ab2`
- Intent: Refactor the number module for readability; behavior must not change.
- Inputs: `9.9999, 's', 4`
- Before (old): return `builtins.str`, `'10.00 s'`
- After (new): return `builtins.str`, `'10.000 s'`
- Saved label: real (reverted bug fix: in-contract behavior change the intent forbids)
- **This check: real.** `precision=4` means four significant digits. `'10.00 s'` has four, `'10.000 s'` has five; the new rounding-carry check only fires at 1000, so the carry from 9.9999 to 10 keeps one digit too many.

Changed lines:

```diff
--- old
+++ new
@@ -46,7 +46,6 @@
     value /= 10**old_bucket
     digits = int(max(0, precision - exponent % 3 - 1))
-    # Absorb a rounding carry (9.999 -> 10.0) by bumping the exponent.
-    if exponent < 30 and round(abs(value), digits) >= 10 ** (exponent % 3 + 1):
-        exponent += 1
+    if exponent < 30 and round(abs(value), digits) >= 1000:
+        exponent += 3 - exponent % 3
         new_bucket = exponent // 3 * 3
         value /= 10 ** (new_bucket - old_bucket)
```

<details><summary>Full old source</summary>

```python
def metric(value: float, unit: str = "", precision: int = 3) -> str:
    """Return a value with a metric SI unit-prefix appended.

    Examples:
        ```pycon
        >>> metric(1500, "V")
        '1.50 kV'
        >>> metric(2e8, "W")
        '200 MW'
        >>> metric(220e-6, "F")
        '220 μF'
        >>> metric(1e-14, precision=4)
        '10.00 f'

        ```

    The unit prefix is always chosen so that non-significant zero digits are required.
    i.e. `123,000` will become `123k` instead of `0.123M` and `1,230,000` will become
    `1.23M` instead of `1230K`. For numbers that are either too huge or too tiny to
    represent without resorting to either leading or trailing zeroes, it falls back to
    `scientific()`.
    ```pycon
    >>> metric(1e40)
    '1.00 x 10⁴⁰'

    ```

    Args:
        value (int, float): Input number.
        unit (str): Optional base unit.
        precision (int): The number of digits the output should contain.

    Returns:
        str:
    """
    import math

    if not math.isfinite(value):
        return _format_not_finite(value)
    exponent = math.floor(math.log10(abs(value))) if value != 0 else 0

    if exponent >= 33 or exponent < -30:
        return scientific(value, precision - 1) + unit

    old_bucket = exponent // 3 * 3
    value /= 10**old_bucket
    digits = int(max(0, precision - exponent % 3 - 1))
    # Absorb a rounding carry (9.999 -> 10.0) by bumping the exponent.
    if exponent < 30 and round(abs(value), digits) >= 10 ** (exponent % 3 + 1):
        exponent += 1
        new_bucket = exponent // 3 * 3
        value /= 10 ** (new_bucket - old_bucket)
        digits = int(max(0, precision - exponent % 3 - 1))

    if exponent >= 3:
        ordinal_ = "kMGTPEZYRQ"[exponent // 3 - 1]
    elif exponent < 0:
        ordinal_ = "mμnpfazyrq"[(-exponent - 1) // 3]
    else:
        ordinal_ = ""
    value_ = format(value, f".{digits}f")
    if not (unit or ordinal_) or unit in ("°", "′", "″"):
        space = ""
    else:
        space = " "

    return f"{value_}{space}{ordinal_}{unit}"
```

</details>

<details><summary>Full new source</summary>

```python
def metric(value: float, unit: str = "", precision: int = 3) -> str:
    """Return a value with a metric SI unit-prefix appended.

    Examples:
        ```pycon
        >>> metric(1500, "V")
        '1.50 kV'
        >>> metric(2e8, "W")
        '200 MW'
        >>> metric(220e-6, "F")
        '220 μF'
        >>> metric(1e-14, precision=4)
        '10.00 f'

        ```

    The unit prefix is always chosen so that non-significant zero digits are required.
    i.e. `123,000` will become `123k` instead of `0.123M` and `1,230,000` will become
    `1.23M` instead of `1230K`. For numbers that are either too huge or too tiny to
    represent without resorting to either leading or trailing zeroes, it falls back to
    `scientific()`.
    ```pycon
    >>> metric(1e40)
    '1.00 x 10⁴⁰'

    ```

    Args:
        value (int, float): Input number.
        unit (str): Optional base unit.
        precision (int): The number of digits the output should contain.

    Returns:
        str:
    """
    import math

    if not math.isfinite(value):
        return _format_not_finite(value)
    exponent = math.floor(math.log10(abs(value))) if value != 0 else 0

    if exponent >= 33 or exponent < -30:
        return scientific(value, precision - 1) + unit

    old_bucket = exponent // 3 * 3
    value /= 10**old_bucket
    digits = int(max(0, precision - exponent % 3 - 1))
    if exponent < 30 and round(abs(value), digits) >= 1000:
        exponent += 3 - exponent % 3
        new_bucket = exponent // 3 * 3
        value /= 10 ** (new_bucket - old_bucket)
        digits = int(max(0, precision - exponent % 3 - 1))

    if exponent >= 3:
        ordinal_ = "kMGTPEZYRQ"[exponent // 3 - 1]
    elif exponent < 0:
        ordinal_ = "mμnpfazyrq"[(-exponent - 1) // 3]
    else:
        ordinal_ = ""
    value_ = format(value, f".{digits}f")
    if not (unit or ordinal_) or unit in ("°", "′", "″"):
        space = ""
    else:
        space = " "

    return f"{value_}{space}{ordinal_}{unit}"
```

</details>

## 4. `more_itertools/more.py::exactly_n`

- Scenario: `more-itertools-replay-adeda34` (replay), repository `more-itertools`, commit `adeda34bd11f`
- Finding id: `b632d0907429`
- Intent: Refactor the more module for readability; behavior must not change.
- Inputs: `[0], 9223372036854775807`
- Before (old): return `builtins.bool`, `False`
- After (new): exception `builtins.ValueError`, `ValueError('Stop argument for islice() must be None or an integer: 0 <= x <= sys.maxsize.')`
- Saved label: real (reverted bug fix: in-contract behavior change the intent forbids)
- Independent label (seed 21): real (For a valid int n=sys.maxsize, islice(n+1) now raises ValueError where the old code returned False.)
- **This check: real.** Borderline but real. `n` is an `int` and `sys.maxsize` is a valid `int`; the old code answers `False` (one item is not `sys.maxsize` items), the new one-liner crashes inside `islice(…, n + 1)`. An unusual value, but in contract.

Changed lines:

```diff
--- old
+++ new
@@ -14,16 +14,3 @@
 
     """
-    iterator = filter(predicate, iterable)
-    if n <= 0:
-        if n < 0:
-            return False
-        for _ in iterator:
-            return False
-        return True
-
-    iterator = islice(iterator, n - 1, None)
-    for _ in iterator:
-        for _ in iterator:
-            return False
-        return True
-    return False
+    return ilen(islice(filter(predicate, iterable), n + 1)) == n
```

<details><summary>Full old source</summary>

```python
def exactly_n(iterable, n, predicate=bool):
    """Return ``True`` if exactly ``n`` items in the iterable are ``True``
    according to the *predicate* function.

        >>> exactly_n([True, True, False], 2)
        True
        >>> exactly_n([True, True, False], 1)
        False
        >>> exactly_n([0, 1, 2, 3, 4, 5], 3, lambda x: x < 3)
        True

    The iterable will be advanced until ``n + 1`` truthy items are encountered,
    so avoid calling it on infinite iterables.

    """
    iterator = filter(predicate, iterable)
    if n <= 0:
        if n < 0:
            return False
        for _ in iterator:
            return False
        return True

    iterator = islice(iterator, n - 1, None)
    for _ in iterator:
        for _ in iterator:
            return False
        return True
    return False
```

</details>

<details><summary>Full new source</summary>

```python
def exactly_n(iterable, n, predicate=bool):
    """Return ``True`` if exactly ``n`` items in the iterable are ``True``
    according to the *predicate* function.

        >>> exactly_n([True, True, False], 2)
        True
        >>> exactly_n([True, True, False], 1)
        False
        >>> exactly_n([0, 1, 2, 3, 4, 5], 3, lambda x: x < 3)
        True

    The iterable will be advanced until ``n + 1`` truthy items are encountered,
    so avoid calling it on infinite iterables.

    """
    return ilen(islice(filter(predicate, iterable), n + 1)) == n
```

</details>

## 5. `more_itertools/more.py::nth_permutation`

- Scenario: `more-itertools-replay-def2d82` (replay), repository `more-itertools`, commit `def2d821c0a1`
- Finding id: `1fccef029c28`
- Intent: Refactor the more module for readability; behavior must not change.
- Inputs: `{'red', 'blue'}, 3, 0`
- Before (old): exception `builtins.IndexError`, `IndexError()`
- After (new): exception `builtins.ValueError`, `ValueError()`
- Saved label: real (reverted bug fix: in-contract behavior change the intent forbids)
- Independent label (seed 21): real (For an int r greater than the pool size the exception changes from IndexError to ValueError.)
- **This check: real.** Borderline but real. `r=3` is larger than the pool of 2, so both versions reject the call; the exception type changes from `IndexError` to `ValueError`. Callers that catch `IndexError` behave differently, and the owner kept the exact-type rule (task 21 review). A human could reasonably call this not real.

Changed lines:

```diff
--- old
+++ new
@@ -10,15 +10,22 @@
         ('h', 'i')
 
-    ``ValueError`` will be raised If *r* is negative.
+    ``ValueError`` will be raised If *r* is negative or greater than the length
+    of *iterable*.
     ``IndexError`` will be raised if the given *index* is invalid.
     """
     pool = list(iterable)
     n = len(pool)
-    if r is None:
-        r = n
-    c = perm(n, r)
+
+    if r is None or r == n:
+        r, c = n, factorial(n)
+    elif not 0 <= r < n:
+        raise ValueError
+    else:
+        c = perm(n, r)
+    assert c > 0  # factorial(n)>0, and r<n so perm(n,r) is never zero
 
     if index < 0:
         index += c
+
     if not 0 <= index < c:
         raise IndexError
```

<details><summary>Full old source</summary>

```python
def nth_permutation(iterable, r, index):
    """Equivalent to ``list(permutations(iterable, r))[index]```

    The subsequences of *iterable* that are of length *r* where order is
    important can be ordered lexicographically. :func:`nth_permutation`
    computes the subsequence at sort position *index* directly, without
    computing the previous subsequences.

        >>> nth_permutation('ghijk', 2, 5)
        ('h', 'i')

    ``ValueError`` will be raised If *r* is negative.
    ``IndexError`` will be raised if the given *index* is invalid.
    """
    pool = list(iterable)
    n = len(pool)
    if r is None:
        r = n
    c = perm(n, r)

    if index < 0:
        index += c
    if not 0 <= index < c:
        raise IndexError

    result = [0] * r
    q = index * factorial(n) // c if r < n else index
    for d in range(1, n + 1):
        q, i = divmod(q, d)
        if 0 <= n - d < r:
            result[n - d] = i
        if q == 0:
            break

    return tuple(map(pool.pop, result))
```

</details>

<details><summary>Full new source</summary>

```python
def nth_permutation(iterable, r, index):
    """Equivalent to ``list(permutations(iterable, r))[index]```

    The subsequences of *iterable* that are of length *r* where order is
    important can be ordered lexicographically. :func:`nth_permutation`
    computes the subsequence at sort position *index* directly, without
    computing the previous subsequences.

        >>> nth_permutation('ghijk', 2, 5)
        ('h', 'i')

    ``ValueError`` will be raised If *r* is negative or greater than the length
    of *iterable*.
    ``IndexError`` will be raised if the given *index* is invalid.
    """
    pool = list(iterable)
    n = len(pool)

    if r is None or r == n:
        r, c = n, factorial(n)
    elif not 0 <= r < n:
        raise ValueError
    else:
        c = perm(n, r)
    assert c > 0  # factorial(n)>0, and r<n so perm(n,r) is never zero

    if index < 0:
        index += c

    if not 0 <= index < c:
        raise IndexError

    result = [0] * r
    q = index * factorial(n) // c if r < n else index
    for d in range(1, n + 1):
        q, i = divmod(q, d)
        if 0 <= n - d < r:
            result[n - d] = i
        if q == 0:
            break

    return tuple(map(pool.pop, result))
```

</details>

## 6. `more_itertools/more.py::nth_permutation`

- Scenario: `more-itertools-replay-def2d82` (replay), repository `more-itertools`, commit `def2d821c0a1`
- Finding id: `2408865d30f9`
- Intent: Refactor the more module for readability; behavior must not change.
- Inputs: `'a', 2, 0`
- Before (old): exception `builtins.IndexError`, `IndexError()`
- After (new): exception `builtins.ValueError`, `ValueError()`
- Saved label: real (reverted bug fix: in-contract behavior change the intent forbids)
- **This check: real.** Same change as the previous item with a string pool of one (`'a'`, `r=2`): `IndexError` becomes `ValueError`. Borderline for the same reason.

Changed lines:

```diff
--- old
+++ new
@@ -10,15 +10,22 @@
         ('h', 'i')
 
-    ``ValueError`` will be raised If *r* is negative.
+    ``ValueError`` will be raised If *r* is negative or greater than the length
+    of *iterable*.
     ``IndexError`` will be raised if the given *index* is invalid.
     """
     pool = list(iterable)
     n = len(pool)
-    if r is None:
-        r = n
-    c = perm(n, r)
+
+    if r is None or r == n:
+        r, c = n, factorial(n)
+    elif not 0 <= r < n:
+        raise ValueError
+    else:
+        c = perm(n, r)
+    assert c > 0  # factorial(n)>0, and r<n so perm(n,r) is never zero
 
     if index < 0:
         index += c
+
     if not 0 <= index < c:
         raise IndexError
```

<details><summary>Full old source</summary>

```python
def nth_permutation(iterable, r, index):
    """Equivalent to ``list(permutations(iterable, r))[index]```

    The subsequences of *iterable* that are of length *r* where order is
    important can be ordered lexicographically. :func:`nth_permutation`
    computes the subsequence at sort position *index* directly, without
    computing the previous subsequences.

        >>> nth_permutation('ghijk', 2, 5)
        ('h', 'i')

    ``ValueError`` will be raised If *r* is negative.
    ``IndexError`` will be raised if the given *index* is invalid.
    """
    pool = list(iterable)
    n = len(pool)
    if r is None:
        r = n
    c = perm(n, r)

    if index < 0:
        index += c
    if not 0 <= index < c:
        raise IndexError

    result = [0] * r
    q = index * factorial(n) // c if r < n else index
    for d in range(1, n + 1):
        q, i = divmod(q, d)
        if 0 <= n - d < r:
            result[n - d] = i
        if q == 0:
            break

    return tuple(map(pool.pop, result))
```

</details>

<details><summary>Full new source</summary>

```python
def nth_permutation(iterable, r, index):
    """Equivalent to ``list(permutations(iterable, r))[index]```

    The subsequences of *iterable* that are of length *r* where order is
    important can be ordered lexicographically. :func:`nth_permutation`
    computes the subsequence at sort position *index* directly, without
    computing the previous subsequences.

        >>> nth_permutation('ghijk', 2, 5)
        ('h', 'i')

    ``ValueError`` will be raised If *r* is negative or greater than the length
    of *iterable*.
    ``IndexError`` will be raised if the given *index* is invalid.
    """
    pool = list(iterable)
    n = len(pool)

    if r is None or r == n:
        r, c = n, factorial(n)
    elif not 0 <= r < n:
        raise ValueError
    else:
        c = perm(n, r)
    assert c > 0  # factorial(n)>0, and r<n so perm(n,r) is never zero

    if index < 0:
        index += c

    if not 0 <= index < c:
        raise IndexError

    result = [0] * r
    q = index * factorial(n) // c if r < n else index
    for d in range(1, n + 1):
        q, i = divmod(q, d)
        if 0 <= n - d < r:
            result[n - d] = i
        if q == 0:
            break

    return tuple(map(pool.pop, result))
```

</details>

## 7. `src/validators/card.py::mastercard`

- Scenario: `validators-replay-a55c62d` (replay), repository `validators`, commit `a55c62ddd300`
- Finding id: `89709f1d9738`
- Intent: Refactor the card module for readability; behavior must not change.
- Inputs: `'2722000000000003'`
- Before (old): return `validators.utils.ValidationError`, `ValidationError(func=mastercard, args={'value': '2722000000000003'})`
- After (new): return `builtins.bool`, `True`
- Saved label: real (reverted bug fix: in-contract behavior change the intent forbids)
- **This check: real.** Mastercard 2-series numbers run from 2221 to 2720. `2722…` is outside that range; the old pattern rejects it, the new `27` prefix accepts it.

Changed lines:

```diff
--- old
+++ new
@@ -17,4 +17,4 @@
         (ValidationError): If `value` is an invalid Mastercard card number.
     """
-    pattern = re.compile(r"^(5[1-5]|222[1-9]|22[3-9][0-9]|2[3-6][0-9]{2}|27[01][0-9]|2720)")
+    pattern = re.compile(r"^(51|52|53|54|55|22|23|24|25|26|27)")
     return card_number(value) and len(value) == 16 and pattern.match(value)
```

<details><summary>Full old source</summary>

```python
@validator
def mastercard(value: str, /):
    """Return whether or not given value is a valid Mastercard card number.

    Examples:
        >>> mastercard('5555555555554444')
        True
        >>> mastercard('4242424242424242')
        ValidationError(func=mastercard, args={'value': '4242424242424242'})

    Args:
        value:
            Mastercard card number string to validate

    Returns:
        (Literal[True]): If `value` is a valid Mastercard card number.
        (ValidationError): If `value` is an invalid Mastercard card number.
    """
    pattern = re.compile(r"^(5[1-5]|222[1-9]|22[3-9][0-9]|2[3-6][0-9]{2}|27[01][0-9]|2720)")
    return card_number(value) and len(value) == 16 and pattern.match(value)
```

</details>

<details><summary>Full new source</summary>

```python
@validator
def mastercard(value: str, /):
    """Return whether or not given value is a valid Mastercard card number.

    Examples:
        >>> mastercard('5555555555554444')
        True
        >>> mastercard('4242424242424242')
        ValidationError(func=mastercard, args={'value': '4242424242424242'})

    Args:
        value:
            Mastercard card number string to validate

    Returns:
        (Literal[True]): If `value` is a valid Mastercard card number.
        (ValidationError): If `value` is an invalid Mastercard card number.
    """
    pattern = re.compile(r"^(51|52|53|54|55|22|23|24|25|26|27)")
    return card_number(value) and len(value) == 16 and pattern.match(value)
```

</details>

## 8. `src/packaging/licenses/__init__.py::canonicalize_license_expression`

- Scenario: `packaging-replay-2c87a33` (replay), repository `packaging`, commit `2c87a33f6658`
- Finding id: `0abb3036400e`
- Intent: Refactor the licenses module for readability; behavior must not change.
- Inputs: `'(LicenseRef-Echo OR licenseref-ECHO) AND LicenseRef-echo'`
- Before (old): return `builtins.str`, `'(LicenseRef-Echo OR LicenseRef-Echo) AND LicenseRef-Echo'`
- After (new): return `builtins.str`, `'(LicenseRef-echo OR LicenseRef-echo) AND LicenseRef-echo'`
- Saved label: real (reverted bug fix: in-contract behavior change the intent forbids)
- **This check: real.** SPDX `LicenseRef-` ids are case-insensitive and the old code keeps the spelling of the first occurrence (`Echo`). The new dict comprehension keeps the last one (`echo`), so the canonical output changes.

Changed lines:

```diff
--- old
+++ new
@@ -38,13 +38,9 @@
     license_expression = raw_license_expression.replace("(", " ( ").replace(")", " ) ")
     licenseref_prefix = "LicenseRef-"
-
-    # The idstring of a LicenseRef- is case-insensitive in SPDX, so all case
-    # variants of one ref use the spelling of the first occurrence.
-    license_refs: dict[str, str] = {}
-    for ref in license_expression.split():
-        if ref.lower().startswith(licenseref_prefix.lower()):
-            license_refs.setdefault(
-                ref.lower(), licenseref_prefix + ref[len(licenseref_prefix) :]
-            )
+    license_refs = {
+        ref.lower(): "LicenseRef-" + ref[len(licenseref_prefix) :]
+        for ref in license_expression.split()
+        if ref.lower().startswith(licenseref_prefix.lower())
+    }
 
     # Normalize to lower case so we can look up licenses/exceptions
```

<details><summary>Full old source</summary>

```python
def canonicalize_license_expression(
    raw_license_expression: str,
) -> NormalizedLicenseExpression:
    """
    This function takes a valid License-Expression, and returns the normalized
    form of it.

    The return type is typed as :class:`NormalizedLicenseExpression`. This
    allows type checkers to help require that a string has passed through this
    function before use.

    :param str raw_license_expression: The License-Expression to canonicalize.
    :raises InvalidLicenseExpression: If the License-Expression is invalid due to an
        invalid/unknown license identifier or invalid syntax.

    .. doctest::

        >>> from packaging.licenses import canonicalize_license_expression
        >>> canonicalize_license_expression("mit")
        'MIT'
        >>> canonicalize_license_expression("mit and (apache-2.0 or bsd-2-clause)")
        'MIT AND (Apache-2.0 OR BSD-2-Clause)'
        >>> canonicalize_license_expression("(mit")
        Traceback (most recent call last):
          ...
        InvalidLicenseExpression: Invalid license expression: '(mit'
        >>> canonicalize_license_expression("Use-it-after-midnight")
        Traceback (most recent call last):
          ...
        InvalidLicenseExpression: Unknown license: 'Use-it-after-midnight'
    """
    if not raw_license_expression:
        message = f"Invalid license expression: {raw_license_expression!r}"
        raise InvalidLicenseExpression(message)

    # Pad any parentheses so tokenization can be achieved by merely splitting on
    # whitespace.
    license_expression = raw_license_expression.replace("(", " ( ").replace(")", " ) ")
    licenseref_prefix = "LicenseRef-"

    # The idstring of a LicenseRef- is case-insensitive in SPDX, so all case
    # variants of one ref use the spelling of the first occurrence.
    license_refs: dict[str, str] = {}
    for ref in license_expression.split():
        if ref.lower().startswith(licenseref_prefix.lower()):
            license_refs.setdefault(
                ref.lower(), licenseref_prefix + ref[len(licenseref_prefix) :]
            )

    # Normalize to lower case so we can look up licenses/exceptions
    # and so boolean operators are Python-compatible.
    license_expression = license_expression.lower()

    tokens = license_expression.split()

    # Rather than implementing a parenthesis/boolean logic parser, create an
    # expression that Python can parse. Everything that is not involved with the
    # grammar itself is replaced with the placeholder `False` and the resultant
    # expression should become a valid Python expression.
    python_tokens = []
    for token in tokens:
        if token not in {"or", "and", "with", "(", ")"}:
            python_tokens.append("False")
        elif token == "with":
            python_tokens.append("or")
        elif (
            token == "("
            and python_tokens
            and python_tokens[-1] not in {"or", "and", "("}
        ) or (token == ")" and python_tokens and python_tokens[-1] == "("):
            message = f"Invalid license expression: {raw_license_expression!r}"
            raise InvalidLicenseExpression(message)
        else:
            python_tokens.append(token)

    python_expression = " ".join(python_tokens)
    try:
        compile(python_expression, "", "eval")
    except SyntaxError:
        message = f"Invalid license expression: {raw_license_expression!r}"
        raise InvalidLicenseExpression(message) from None

    # Take a final pass to check for unknown licenses/exceptions.
    normalized_tokens = []
    last_license_start = False
    for index, token in enumerate(tokens):
        if token in {"or", "and", "with", "(", ")"}:
            if token == "with" and (
                not last_license_start
                or index + 1 == len(tokens)
                or tokens[index + 1] in {"or", "and", "with", "(", ")"}
            ):
                message = f"Invalid license expression: {raw_license_expression!r}"
                raise InvalidLicenseExpression(message)
            normalized_tokens.append(token.upper())
            last_license_start = False
            continue

        if normalized_tokens and normalized_tokens[-1] == "WITH":
            if token not in EXCEPTIONS:
                message = f"Unknown license exception: {token!r}"
                raise InvalidLicenseExpression(message)

            normalized_tokens.append(EXCEPTIONS[token]["id"])
            last_license_start = False
        else:
            if token.endswith("+"):
                final_token = token[:-1]
                suffix = "+"
            else:
                final_token = token
                suffix = ""

            if final_token.startswith("licenseref-"):
                license_ref_id = final_token[len("licenseref-") :]
                if suffix or not license_ref_allowed.match(license_ref_id):
                    message = f"Invalid licenseref: {token!r}"
                    raise InvalidLicenseExpression(message)
                normalized_tokens.append(license_refs[final_token])
            else:
                if final_token not in LICENSES:
                    message = f"Unknown license: {final_token!r}"
                    raise InvalidLicenseExpression(message)
                normalized_tokens.append(LICENSES[final_token]["id"] + suffix)
            last_license_start = True

    normalized_expression = " ".join(normalized_tokens)

    return cast(
        "NormalizedLicenseExpression",
        normalized_expression.replace("( ", "(").replace(" )", ")"),
    )
```

</details>

<details><summary>Full new source</summary>

```python
def canonicalize_license_expression(
    raw_license_expression: str,
) -> NormalizedLicenseExpression:
    """
    This function takes a valid License-Expression, and returns the normalized
    form of it.

    The return type is typed as :class:`NormalizedLicenseExpression`. This
    allows type checkers to help require that a string has passed through this
    function before use.

    :param str raw_license_expression: The License-Expression to canonicalize.
    :raises InvalidLicenseExpression: If the License-Expression is invalid due to an
        invalid/unknown license identifier or invalid syntax.

    .. doctest::

        >>> from packaging.licenses import canonicalize_license_expression
        >>> canonicalize_license_expression("mit")
        'MIT'
        >>> canonicalize_license_expression("mit and (apache-2.0 or bsd-2-clause)")
        'MIT AND (Apache-2.0 OR BSD-2-Clause)'
        >>> canonicalize_license_expression("(mit")
        Traceback (most recent call last):
          ...
        InvalidLicenseExpression: Invalid license expression: '(mit'
        >>> canonicalize_license_expression("Use-it-after-midnight")
        Traceback (most recent call last):
          ...
        InvalidLicenseExpression: Unknown license: 'Use-it-after-midnight'
    """
    if not raw_license_expression:
        message = f"Invalid license expression: {raw_license_expression!r}"
        raise InvalidLicenseExpression(message)

    # Pad any parentheses so tokenization can be achieved by merely splitting on
    # whitespace.
    license_expression = raw_license_expression.replace("(", " ( ").replace(")", " ) ")
    licenseref_prefix = "LicenseRef-"
    license_refs = {
        ref.lower(): "LicenseRef-" + ref[len(licenseref_prefix) :]
        for ref in license_expression.split()
        if ref.lower().startswith(licenseref_prefix.lower())
    }

    # Normalize to lower case so we can look up licenses/exceptions
    # and so boolean operators are Python-compatible.
    license_expression = license_expression.lower()

    tokens = license_expression.split()

    # Rather than implementing a parenthesis/boolean logic parser, create an
    # expression that Python can parse. Everything that is not involved with the
    # grammar itself is replaced with the placeholder `False` and the resultant
    # expression should become a valid Python expression.
    python_tokens = []
    for token in tokens:
        if token not in {"or", "and", "with", "(", ")"}:
            python_tokens.append("False")
        elif token == "with":
            python_tokens.append("or")
        elif (
            token == "("
            and python_tokens
            and python_tokens[-1] not in {"or", "and", "("}
        ) or (token == ")" and python_tokens and python_tokens[-1] == "("):
            message = f"Invalid license expression: {raw_license_expression!r}"
            raise InvalidLicenseExpression(message)
        else:
            python_tokens.append(token)

    python_expression = " ".join(python_tokens)
    try:
        compile(python_expression, "", "eval")
    except SyntaxError:
        message = f"Invalid license expression: {raw_license_expression!r}"
        raise InvalidLicenseExpression(message) from None

    # Take a final pass to check for unknown licenses/exceptions.
    normalized_tokens = []
    last_license_start = False
    for index, token in enumerate(tokens):
        if token in {"or", "and", "with", "(", ")"}:
            if token == "with" and (
                not last_license_start
                or index + 1 == len(tokens)
                or tokens[index + 1] in {"or", "and", "with", "(", ")"}
            ):
                message = f"Invalid license expression: {raw_license_expression!r}"
                raise InvalidLicenseExpression(message)
            normalized_tokens.append(token.upper())
            last_license_start = False
            continue

        if normalized_tokens and normalized_tokens[-1] == "WITH":
            if token not in EXCEPTIONS:
                message = f"Unknown license exception: {token!r}"
                raise InvalidLicenseExpression(message)

            normalized_tokens.append(EXCEPTIONS[token]["id"])
            last_license_start = False
        else:
            if token.endswith("+"):
                final_token = token[:-1]
                suffix = "+"
            else:
                final_token = token
                suffix = ""

            if final_token.startswith("licenseref-"):
                license_ref_id = final_token[len("licenseref-") :]
                if suffix or not license_ref_allowed.match(license_ref_id):
                    message = f"Invalid licenseref: {token!r}"
                    raise InvalidLicenseExpression(message)
                normalized_tokens.append(license_refs[final_token])
            else:
                if final_token not in LICENSES:
                    message = f"Unknown license: {final_token!r}"
                    raise InvalidLicenseExpression(message)
                normalized_tokens.append(LICENSES[final_token]["id"] + suffix)
            last_license_start = True

    normalized_expression = " ".join(normalized_tokens)

    return cast(
        "NormalizedLicenseExpression",
        normalized_expression.replace("( ", "(").replace(" )", ")"),
    )
```

</details>

## 9. `more_itertools/more.py::nth_combination_with_replacement`

- Scenario: `more-itertools-replay-06f3181` (replay), repository `more-itertools`, commit `06f31819121e`
- Finding id: `fe94b46bb518`
- Intent: Refactor the more module for readability; behavior must not change.
- Inputs: `[1, 2], 3, 0`
- Before (old): return `builtins.tuple`, `(1, 1, 1)`
- After (new): exception `builtins.ValueError`, `ValueError()`
- Saved label: real (reverted bug fix: in-contract behavior change the intent forbids)
- Independent label (seed 21): real (New r>n check wrongly rejects a valid combination-with-replacement call that used to return (1, 1, 1).)
- **This check: real.** Same function as item 2: `r=3` with a pool of 2 is valid with replacement (`(1, 1, 1)`), the new code raises `ValueError`.

Changed lines:

```diff
--- old
+++ new
@@ -12,16 +12,19 @@
         (0, 1, 1)
 
-    ``ValueError`` will be raised If *r* is negative.
+    ``ValueError`` will be raised If *r* is negative or greater than the length
+    of *iterable*.
     ``IndexError`` will be raised if the given *index* is invalid.
     """
     pool = tuple(iterable)
     n = len(pool)
-    if r < 0:
+    if (r < 0) or (r > n):
         raise ValueError
-    c = comb(n + r - 1, r) if n else 0 if r else 1
+
+    c = comb(n + r - 1, r)
 
     if index < 0:
         index += c
-    if not 0 <= index < c:
+
+    if (index < 0) or (index >= c):
         raise IndexError
 
```

<details><summary>Full old source</summary>

```python
def nth_combination_with_replacement(iterable, r, index):
    """Equivalent to
    ``list(combinations_with_replacement(iterable, r))[index]``.


    The subsequences with repetition of *iterable* that are of length *r* can
    be ordered lexicographically. :func:`nth_combination_with_replacement`
    computes the subsequence at sort position *index* directly, without
    computing the previous subsequences with replacement.

        >>> nth_combination_with_replacement(range(5), 3, 5)
        (0, 1, 1)

    ``ValueError`` will be raised If *r* is negative.
    ``IndexError`` will be raised if the given *index* is invalid.
    """
    pool = tuple(iterable)
    n = len(pool)
    if r < 0:
        raise ValueError
    c = comb(n + r - 1, r) if n else 0 if r else 1

    if index < 0:
        index += c
    if not 0 <= index < c:
        raise IndexError

    result = []
    i = 0
    while r:
        r -= 1
        while n >= 0:
            num_combs = comb(n + r - 1, r)
            if index < num_combs:
                break
            n -= 1
            i += 1
            index -= num_combs
        result.append(pool[i])

    return tuple(result)
```

</details>

<details><summary>Full new source</summary>

```python
def nth_combination_with_replacement(iterable, r, index):
    """Equivalent to
    ``list(combinations_with_replacement(iterable, r))[index]``.


    The subsequences with repetition of *iterable* that are of length *r* can
    be ordered lexicographically. :func:`nth_combination_with_replacement`
    computes the subsequence at sort position *index* directly, without
    computing the previous subsequences with replacement.

        >>> nth_combination_with_replacement(range(5), 3, 5)
        (0, 1, 1)

    ``ValueError`` will be raised If *r* is negative or greater than the length
    of *iterable*.
    ``IndexError`` will be raised if the given *index* is invalid.
    """
    pool = tuple(iterable)
    n = len(pool)
    if (r < 0) or (r > n):
        raise ValueError

    c = comb(n + r - 1, r)

    if index < 0:
        index += c

    if (index < 0) or (index >= c):
        raise IndexError

    result = []
    i = 0
    while r:
        r -= 1
        while n >= 0:
            num_combs = comb(n + r - 1, r)
            if index < num_combs:
                break
            n -= 1
            i += 1
            index -= num_combs
        result.append(pool[i])

    return tuple(result)
```

</details>

## 10. `boltons/strutils.py::singularize`

- Scenario: `boltons-replay-1e61524` (replay), repository `boltons`, commit `1e61524a798e`
- Finding id: `2a1e53717c0a`
- Intent: Refactor the strutils module for readability; behavior must not change.
- Inputs: `'fuss'`
- Before (old): return `builtins.str`, `'fuss'`
- After (new): return `builtins.str`, `'fus'`
- Saved label: real (reverted bug fix: in-contract behavior change the intent forbids)
- **This check: real.** `fuss` is singular and must stay `fuss`; the new code strips the trailing `s` (`fus`). The removed branch's comment describes exactly this case.

Changed lines:

```diff
--- old
+++ new
@@ -28,11 +28,4 @@
     elif word.endswith('es') and word[-3] == 's':
         singular = word[:-2]
-    elif word.endswith('ss'):
-        # Words ending in a double 's' (glass, boss, kiss) are already
-        # singular; their plurals end in 'sses' and are handled above. Do
-        # not blindly strip the trailing 's', which would produce 'glas',
-        # 'bos', 'kis' and break idempotency (singularize('Glasses') ==
-        # 'Glass', but 'Glass' must stay 'Glass').
-        return orig_word
     else:
         singular = word[:-1]
```

<details><summary>Full old source</summary>

```python
def singularize(word):
    """Semi-intelligently converts an English plural *word* to its
    singular form, preserving case pattern.

    >>> singularize('chances')
    'chance'
    >>> singularize('Activities')
    'Activity'
    >>> singularize('Glasses')
    'Glass'
    >>> singularize('FEET')
    'FOOT'

    """
    orig_word, word = word, word.strip().lower()
    if not word or word in _IRR_S2P:
        return orig_word

    irr_singular = _IRR_P2S.get(word)
    if irr_singular:
        singular = irr_singular
    elif not word.endswith('s'):
        return orig_word
    elif len(word) == 2:
        singular = word[:-1]  # or just return word?
    elif word.endswith('ies') and word[-4:-3] not in 'aeiou':
        singular = word[:-3] + 'y'
    elif word.endswith('es') and word[-3] == 's':
        singular = word[:-2]
    elif word.endswith('ss'):
        # Words ending in a double 's' (glass, boss, kiss) are already
        # singular; their plurals end in 'sses' and are handled above. Do
        # not blindly strip the trailing 's', which would produce 'glas',
        # 'bos', 'kis' and break idempotency (singularize('Glasses') ==
        # 'Glass', but 'Glass' must stay 'Glass').
        return orig_word
    else:
        singular = word[:-1]
    return _match_case(orig_word, singular)
```

</details>

<details><summary>Full new source</summary>

```python
def singularize(word):
    """Semi-intelligently converts an English plural *word* to its
    singular form, preserving case pattern.

    >>> singularize('chances')
    'chance'
    >>> singularize('Activities')
    'Activity'
    >>> singularize('Glasses')
    'Glass'
    >>> singularize('FEET')
    'FOOT'

    """
    orig_word, word = word, word.strip().lower()
    if not word or word in _IRR_S2P:
        return orig_word

    irr_singular = _IRR_P2S.get(word)
    if irr_singular:
        singular = irr_singular
    elif not word.endswith('s'):
        return orig_word
    elif len(word) == 2:
        singular = word[:-1]  # or just return word?
    elif word.endswith('ies') and word[-4:-3] not in 'aeiou':
        singular = word[:-3] + 'y'
    elif word.endswith('es') and word[-3] == 's':
        singular = word[:-2]
    else:
        singular = word[:-1]
    return _match_case(orig_word, singular)
```

</details>
