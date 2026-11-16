"""Exit codes. Part of awsemu's stable interface (see docs/scripting.md).

0  OK           the command did what was asked
1  FAILED       it ran but something failed: an AWS error, a failing Lambda
                function or Step Functions execution, a resource not found, a
                seed resource that couldn't be applied, the emulator not starting
2  USAGE        nothing was done: bad arguments, invalid seed or awsemu.toml
                (Click uses 2 for usage errors too)
3  NOT_HEALTHY  only 'awsemu status': the emulator isn't running or isn't healthy
"""

OK = 0
FAILED = 1
USAGE = 2
NOT_HEALTHY = 3
