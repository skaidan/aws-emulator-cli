"""Explain a failed call from the proxy's log: an emulator difference, or the code under test?

The answer is a judgement from evidence, never a certainty:

* the proxy injected the error -> ``injected``;
* a fidelity test fails at the same operation with the same answer from the emulator
  (status and error code) -> ``known_difference``;
* fidelity tests fail at that operation, with another answer -> ``possible_difference``;
* the emulator answered with a server error or "not implemented" -> ``emulator_gap``;
* the operation's fidelity tests pass and the error is the kind AWS returns for a bad
  request -> ``likely_your_code``;
* no fidelity tests cover the operation -> ``unknown``.
"""

from __future__ import annotations

import re

from . import check as chk

GAP_CODES = {
    "NotImplemented",
    "NotImplementedException",
    "UnknownOperationException",
    "InvalidAction",
    "UnsupportedOperation",
    "UnsupportedOperationException",
    "InternalFailure",
    "InternalError",
    "InternalServerError",
    "InternalServerException",
    "ServiceUnavailable",
    "EmulatorUnreachable",
}

ADVICE = {
    "injected": "The proxy made this error on purpose (a fault rule). Remove the rule if you didn't mean it: "
    "awsemu proxy faults clear.",
    "known_difference": "The emulator is known to answer this differently from AWS. Your code may be right: "
    "check the difference, and work around it or wait for a fix (upgrading may help).",
    "possible_difference": "The emulator has known differences in this operation, but none with this answer. "
    "Compare the request with the operation's reference before blaming either side.",
    "emulator_gap": "The emulator answered with a server error or doesn't support this: probably not your code. "
    "If AWS supports the request, report it: awsemu report CALL.",
    "likely_your_code": "The emulator's tests for this operation pass and this is the error AWS returns for a "
    "request it rejects: check the parameters, the resources the call needs and the order "
    "of the calls.",
    "unknown": "No fidelity tests cover this operation, so there's no evidence either way. Check the request "
    "against the operation's reference; if AWS accepts it, report it: awsemu report CALL.",
    "succeeded": "The call succeeded (HTTP status below 400). If the response itself looks wrong, compare it "
    "with the operation's reference.",
}


def _matches(answer: str | None, call: dict) -> bool:
    """Does a test's "emulator answered" text (``400 ValidationException``) match this call?"""
    if not answer:
        return False
    status, error = str(call.get("status") or ""), call.get("error") or ""
    tokens = set(re.split(r"[\s,;:()]+", answer))
    if error and error in tokens:
        return True
    return bool(status) and status in tokens and not error


def explain(call: dict, index: chk.Index, release: str, suite: str, with_issues: bool = True) -> dict:
    service, operation = call.get("service") or "", call.get("operation") or ""
    out: dict = {
        "call": {
            k: call.get(k)
            for k in ("id", "time", "service", "operation", "resource", "status", "error", "fault", "request_id")
        },
        "release": release,
        "fidelity_tests": suite,
        "operation": None,
        "tests": 0,
        "passed": 0,
        "differences": [],
        "matching": [],
        "verdict": "",
        "advice": "",
    }

    def done(verdict: str) -> dict:
        out["verdict"], out["advice"] = verdict, ADVICE[verdict]
        return out

    if call.get("fault"):
        return done("injected")
    if not service or not operation:
        return done("unknown")

    result, _unknown = chk.scan_from_calls([call], index)
    report = chk.analyze(result, index, release, suite)
    op = next((o for o in report.operations if o.operation.split(":", 1)[1] == operation), None)
    if op is None:
        out["operation"] = f"{index.names.resolve(service) or service}:{operation}"
    else:
        out["operation"], out["tests"], out["passed"] = op.operation, op.tests, op.passed
        if with_issues and op.differences:
            try:
                chk.attach_issues(report)
            except Exception:
                pass
        at_op = [d for d in op.differences if d.at_operation]
        out["differences"] = [d.as_dict(suite) for d in at_op]
        out["matching"] = [d["test"] for d in out["differences"] if _matches(d["actual"], call)]

    status = int(call.get("status") or 0)
    if out["matching"]:  # also a success where AWS would have failed
        return done("known_difference")
    if 0 < status < 400 and not call.get("error"):
        return done("succeeded")
    if out["differences"]:
        return done("possible_difference")
    if status >= 500 or status == 0 or (call.get("error") or "") in GAP_CODES:
        return done("emulator_gap")
    if out["tests"]:
        return done("likely_your_code")
    return done("unknown")
