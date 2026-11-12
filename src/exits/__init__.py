"""
exits
Close positions safely: close_position for one (a signal sell), run_exits once per cycle for the end of the day
"""

#Local Imports
from exits.close import ExitResult, close_position, remaining_shares
from exits.sweep import ExitReport, close_time, run_exits
from exits.watch import ExitWatch
