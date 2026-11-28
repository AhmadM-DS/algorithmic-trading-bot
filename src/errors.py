"""
errors.py
Exception lists shared by every package that reads outside data; imports nothing from the bot
"""

UNREADABLE_ERRORS = (KeyError, TypeError, ValueError, ArithmeticError, AttributeError)
"""What reading a field of outside data can raise: a missing key, a wrong type or value, a bad number
(decimal.InvalidOperation is an ArithmeticError), or a value that isn't a dict (AttributeError)"""
