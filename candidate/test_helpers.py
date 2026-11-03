"""Reusable helpers for the credit-redemption audit (Python stdlib only).

This module never modifies the model under audit or the supplied inputs. It
provides: loading of the original model, state reset, type-strict state diffs,
action/sequence execution with full before/after snapshots, CR6 invariant
checks, and readable assertion results.

Run the helpers' own self-checks with:  python -B candidate/test_helpers.py
"""
import copy
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
INPUTS = ROOT / "inputs"

# Result statuses. "policy" checks end in PASS or FAIL (FAIL = policy violation).
# "defect" checks end in CONFIRMED or NOT_REPRODUCED. Either may be INCONCLUSIVE
# (evidence insufficient) or ERROR (the checker itself or its input broke).
PASS, FAIL = "PASS", "FAIL"
CONFIRMED, NOT_REPRODUCED = "CONFIRMED", "NOT_REPRODUCED"
INCONCLUSIVE, ERROR = "INCONCLUSIVE", "ERROR"

ABSENT = "<absent>"


# --------------------------------------------------------------------------- loading
def load_input(name):
    """Load a supplied JSON input (e.g. 'state.json') from inputs/."""
    return json.loads((INPUTS / name).read_text(encoding="utf-8"))


def load_model():
    """Import the ORIGINAL inputs/credit_model.py without touching sys.path."""
    spec = importlib.util.spec_from_file_location(
        "credit_model_under_audit", INPUTS / "credit_model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- state
def fresh_state(initial, offer_caps):
    """Independent deep copy of `initial` with `offer_caps` applied (as replay() does)."""
    state = copy.deepcopy(initial)
    for offer, cap in offer_caps.items():
        state["offers"][offer]["cap"] = cap
    return state


def diff_state(before, after, path=""):
    """Type-strict structural diff -> list of (path, before, after).

    Plain `==` is not enough: in Python `True == 1`, so a bool/int swap would be
    invisible. Here values of different types always differ.
    """
    if type(before) is not type(after):
        return [(path or "<root>", before, after)]
    if isinstance(before, dict):
        out = []
        for key in sorted(set(before) | set(after), key=str):
            sub = f"{path}.{key}" if path else str(key)
            if key not in before:
                out.append((sub, ABSENT, after[key]))
            elif key not in after:
                out.append((sub, before[key], ABSENT))
            else:
                out.extend(diff_state(before[key], after[key], sub))
        return out
    if isinstance(before, (list, tuple)):
        if len(before) != len(after):
            return [(path or "<root>", before, after)]
        out = []
        for i, (b, a) in enumerate(zip(before, after)):
            out.extend(diff_state(b, a, f"{path}[{i}]"))
        return out
    return [] if before == after else [(path or "<root>", before, after)]


def format_diff(diffs):
    """Readable one-line-per-change rendering of diff_state() output."""
    if not diffs:
        return "no change"
    return "; ".join(f"{p}: {b!r} -> {a!r}" for p, b, a in diffs)


# --------------------------------------------------------------------------- execution
def run_action(handler, state, action):
    """Run one action on `state` (mutated in place by the handler, as the model does).

    Returns a step record with deep-copied snapshots, so later mutations of
    `state` cannot alter the evidence. A handler exception is recorded, not raised.
    """
    before = copy.deepcopy(state)
    response, exception = None, None
    try:
        response = handler(state, copy.deepcopy(action))
    except Exception as exc:  # the model crashing is evidence, not a checker crash
        exception = f"{type(exc).__name__}: {exc}"
    return {
        "id": action.get("id"),
        "action": copy.deepcopy(action),
        "before": before,
        "response": copy.deepcopy(response),
        "after": copy.deepcopy(state),
        "exception": exception,
        "changes": diff_state(before, state),
    }


def run_sequence(handler, initial, offer_caps, actions):
    """Run ordered actions on ONE fresh state; state is shared only inside the sequence."""
    state = fresh_state(initial, offer_caps)
    start = copy.deepcopy(state)
    steps = [run_action(handler, state, action) for action in actions]
    return {"start": start, "steps": steps, "final": state}


# --------------------------------------------------------------------------- CR6
def invariant_violations(start, state):
    """CR6 checks on `state` against the case's `start` state. Empty list = holds."""
    found = []
    if diff_state(start["offers"], state["offers"]):
        found.append("offers mutated: " + format_diff(diff_state(start["offers"], state["offers"])))

    spent = {account: 0 for account in start["accounts"]}
    for key, amount in state["claims"].items():
        account = key.split("/", 1)[0]
        if account not in spent:
            found.append(f"claim {key!r} for unknown account")
        elif isinstance(amount, (int, float)):
            spent[account] += amount
        else:
            found.append(f"claim {key!r} has non-numeric amount {amount!r}")
    for account, initial_balance in start["accounts"].items():
        actual = state["accounts"].get(account)
        expected = initial_balance - spent[account]
        if actual != expected:
            found.append(f"conservation {account}: expected {expected}, actual {actual}")
        if isinstance(actual, (int, float)) and actual < 0:
            found.append(f"negative balance {account}: {actual}")

    by_claim = {}
    for rid, record in state["requests"].items():
        account, offer, amount = record["payload"]
        key = f"{account}/{offer}"
        if key in by_claim:
            found.append(f"claim {key!r} has more than one successful request")
        by_claim[key] = amount
    for key in sorted(set(state["claims"]) - set(by_claim)):
        found.append(f"claim {key!r} has no request record")
    for key in sorted(set(by_claim) - set(state["claims"])):
        found.append(f"request for {key!r} has no claim")
    for key in sorted(set(by_claim) & set(state["claims"])):
        if diff_state(state["claims"][key], by_claim[key]):
            found.append(f"claim {key!r} amount {state['claims'][key]!r} differs from request payload {by_claim[key]!r}")
    return found


# --------------------------------------------------------------------------- results
def make_result(check_id, kind, rule, description, ok, expected, actual, detail=""):
    """Build a result. kind='policy' -> PASS/FAIL; kind='defect' -> CONFIRMED/NOT_REPRODUCED;
    ok=None -> INCONCLUSIVE."""
    if kind not in ("policy", "defect"):
        raise ValueError(f"unknown kind {kind!r}")
    if ok is None:
        status = INCONCLUSIVE
    elif kind == "policy":
        status = PASS if ok else FAIL
    else:
        status = CONFIRMED if ok else NOT_REPRODUCED
    return {"id": check_id, "kind": kind, "rule": rule, "description": description,
            "status": status, "expected": expected, "actual": actual, "detail": detail}


def error_result(check_id, kind, rule, description, detail):
    """Result for a checker/input problem; never confuse with a model defect."""
    return {"id": check_id, "kind": kind, "rule": rule, "description": description,
            "status": ERROR, "expected": None, "actual": None, "detail": detail}


def format_result(result):
    line = f"[{result['status']}] {result['id']} ({result['rule']}) {result['description']}"
    if result["expected"] is not None or result["actual"] is not None:
        line += f" | expected={result['expected']!r} actual={result['actual']!r}"
    if result["detail"]:
        line += f" | {result['detail']}"
    return line


# --------------------------------------------------------------------------- self-checks
def _toy_initial():
    return {"accounts": {"A": 100, "B": 20},
            "offers": {"spring": {"cap": 30, "eligible": ["A", "B"]}},
            "claims": {}, "requests": {}}


def _check_diff_is_type_strict():
    assert diff_state({"c": {"A/x": 1}}, {"c": {"A/x": True}}), "bool vs int must differ"
    assert diff_state({"a": 1}, {"a": 1.0}), "int vs float must differ"
    assert not diff_state({"a": [1, {"b": 2}]}, {"a": [1, {"b": 2}]}), "equal states must not differ"


def _check_diff_locates_changes():
    d = diff_state({"accounts": {"A": 100}, "claims": {}},
                   {"accounts": {"A": 70}, "claims": {"A/spring": 30}})
    assert ("accounts.A", 100, 70) in d and ("claims.A/spring", ABSENT, 30) in d, d
    assert ("claims.A/spring", 30, ABSENT) in diff_state({"claims": {"A/spring": 30}}, {"claims": {}})


def _check_run_action_snapshots_are_independent():
    state = _toy_initial()

    def handler(s, a):
        s["claims"]["A/spring"] = 5
        return {"code": "ok"}

    step = run_action(handler, state, {"id": "T1"})
    state["claims"]["later"] = 1  # mutate live state afterwards
    assert step["before"]["claims"] == {}, "before snapshot must be a deep copy"
    assert step["after"]["claims"] == {"A/spring": 5}, "after snapshot must not follow live state"
    assert step["changes"] == [("claims.A/spring", ABSENT, 5)], step["changes"]


def _check_mutation_on_denial_is_detected():
    def pure_denial(s, a):
        return {"code": "invalid"}

    def mutating_denial(s, a):
        s["claims"]["B/spring"] = 30
        return {"code": "invalid"}

    assert run_action(pure_denial, _toy_initial(), {"id": "p"})["changes"] == []
    assert run_action(mutating_denial, _toy_initial(), {"id": "m"})["changes"], "mutation must be seen"


def _check_handler_exception_is_recorded():
    def boom(s, a):
        raise ValueError("boom")

    step = run_action(boom, _toy_initial(), {"id": "x"})
    assert step["exception"] == "ValueError: boom" and step["response"] is None


def _check_reset_between_sequences():
    initial = _toy_initial()
    pristine = copy.deepcopy(initial)

    def spend(s, a):
        s["accounts"]["A"] -= 10
        return {"code": "ok"}

    first = run_sequence(spend, initial, {"spring": 40}, [{"id": "1"}, {"id": "2"}])
    second = run_sequence(spend, initial, {"spring": 40}, [{"id": "1"}])
    assert first["final"]["accounts"]["A"] == 80 and second["final"]["accounts"]["A"] == 90, "state leaked"
    assert second["start"]["offers"]["spring"]["cap"] == 40, "caps must be applied"
    assert not diff_state(initial, pristine), "initial state must never be mutated"


def _check_invariants():
    start = _toy_initial()
    good = copy.deepcopy(start)
    good["accounts"]["A"] = 70
    good["claims"]["A/spring"] = 30
    good["requests"]["R1"] = {"payload": ["A", "spring", 30], "response": {"code": "ok", "amount": 30}}
    assert invariant_violations(start, good) == [], invariant_violations(start, good)

    double_debit = copy.deepcopy(good)
    double_debit["accounts"]["A"] = 40
    assert any("conservation A" in v for v in invariant_violations(start, double_debit))

    negative = copy.deepcopy(good)
    negative["accounts"]["A"] = -5
    assert any("negative balance" in v for v in invariant_violations(start, negative))

    orphan_claim = copy.deepcopy(good)
    orphan_claim["requests"] = {}
    assert any("no request record" in v for v in invariant_violations(start, orphan_claim))

    orphan_request = copy.deepcopy(good)
    orphan_request["claims"] = {}
    orphan_request["accounts"]["A"] = 100
    assert any("no claim" in v for v in invariant_violations(start, orphan_request))

    offer_changed = copy.deepcopy(good)
    offer_changed["offers"]["spring"]["cap"] = 99
    assert any("offers mutated" in v for v in invariant_violations(start, offer_changed))

    bool_claim = copy.deepcopy(good)
    bool_claim["claims"]["A/spring"] = True
    assert any("differs from request payload" in v for v in invariant_violations(start, bool_claim))


def _check_result_statuses():
    assert make_result("i", "policy", "CR1", "d", True, 1, 1)["status"] == PASS
    assert make_result("i", "policy", "CR1", "d", False, 1, 2)["status"] == FAIL
    assert make_result("i", "defect", "CR5", "d", True, 1, 2)["status"] == CONFIRMED
    assert make_result("i", "defect", "CR5", "d", False, 1, 1)["status"] == NOT_REPRODUCED
    assert make_result("i", "policy", "CR1", "d", None, 1, 1)["status"] == INCONCLUSIVE
    assert error_result("i", "policy", "CR1", "d", "x")["status"] == ERROR
    try:
        make_result("i", "other", "CR1", "d", True, 1, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown kind must be rejected")


def _check_adapter_matches_original_replay():
    """Cross-validate our runner against the model's own replay() on S1 and S2."""
    model = load_model()
    initial = load_input("state.json")
    for name in ("sequences-one.json", "sequences-two.json"):
        corpus = load_input(name)
        expected = model.replay(initial, corpus)
        for exp_case, case in zip(expected, corpus["cases"]):
            ours = run_sequence(model.redeem, initial, corpus["offer_caps"], case["actions"])
            assert [s["id"] for s in ours["steps"]] == [s["id"] for s in exp_case["steps"]]
            for mine, theirs in zip(ours["steps"], exp_case["steps"]):
                assert not diff_state(theirs["before"], mine["before"]), (name, mine["id"], "before")
                assert not diff_state(theirs["response"], mine["response"]), (name, mine["id"], "response")
                assert not diff_state(theirs["after"], mine["after"]), (name, mine["id"], "after")
            assert not diff_state(exp_case["final"], ours["final"]), (name, case["id"], "final")


SELF_CHECKS = [
    _check_diff_is_type_strict,
    _check_diff_locates_changes,
    _check_run_action_snapshots_are_independent,
    _check_mutation_on_denial_is_detected,
    _check_handler_exception_is_recorded,
    _check_reset_between_sequences,
    _check_invariants,
    _check_result_statuses,
    _check_adapter_matches_original_replay,
]


def run_self_checks():
    failures = 0
    for check in SELF_CHECKS:
        try:
            check()
            print(f"[PASS] {check.__name__}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {check.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(SELF_CHECKS) - failures}/{len(SELF_CHECKS)} helper self-checks passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if run_self_checks() else 0)