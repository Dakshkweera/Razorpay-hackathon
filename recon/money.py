"""Money in this system is an integer number of paise. Never a float.

Python's ``int`` is arbitrary precision, so addition and subtraction of paise can
never drift. The only operation that could leave integer space is applying a rate
(a fee percentage, GST), and every such operation in the codebase goes through
:func:`mul_rate` below, which does the multiply in integers and rounds explicitly.

That is the whole guarantee: there is exactly one rounding site in the system, and
it is stated rather than implied.
"""

from typing import NewType

Paise = NewType("Paise", int)

#: Rates are basis points: 1 bps = 0.01%. 80 bps = 0.80%, 1800 bps = 18%.
BPS_DENOMINATOR = 10_000


def mul_rate(amount: Paise, bps: int) -> Paise:
    """Apply a basis-point rate to an amount, rounding half away from zero.

    The multiplication happens before the division and both operands are integers,
    so no floating point is involved at any stage. Rounding is applied to the
    magnitude and the sign is reattached, which keeps ``mul_rate(-x, r)`` exactly
    equal to ``-mul_rate(x, r)``. Asymmetric rounding around zero is a classic
    source of one-paise reconciliation breaks.
    """
    if bps < 0:
        raise ValueError(f"rate must be non-negative, got {bps} bps")
    sign = -1 if amount < 0 else 1
    quotient, remainder = divmod(abs(int(amount)) * bps, BPS_DENOMINATOR)
    if remainder * 2 >= BPS_DENOMINATOR:
        quotient += 1
    return Paise(sign * quotient)


def paise(value: int | str) -> Paise:
    """Coerce a CSV field to paise, rejecting anything that is not a whole number.

    A value like ``"249900.0"`` is refused rather than silently truncated: a decimal
    point in a paise column means the upstream file is not what we think it is, and
    guessing is how reconciliation systems start lying.
    """
    if isinstance(value, int):
        return Paise(value)
    text = value.strip()
    if not text:
        return Paise(0)
    if not (text.lstrip("-").isdigit()):
        raise ValueError(f"amount is not an integer number of paise: {value!r}")
    return Paise(int(text))


def format_inr(amount: Paise) -> str:
    """Render paise as rupees with Indian digit grouping, e.g. ``₹46,82,431.00``."""
    sign = "-" if amount < 0 else ""
    rupees, remainder = divmod(abs(int(amount)), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{sign}₹{digits}.{remainder:02d}"
