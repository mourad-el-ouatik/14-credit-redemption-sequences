"""Phase 4: defect-characterization tests (stdlib only).

Each test replays a witness (a supplied S1 case or a scenario from
candidate/scenarios.json) on the handler under test and asks one question:
"is this specific vulnerable behaviour reproduced?" CONFIRMED means yes,
NOT_REPRODUCED means no. In every result, `expected` is what the POLICY requires,
`actual` is what was observed, and `detail` carries the exact action-by-action
evidence (response + every state change).

Run:  python -B candidate/defect_tests.py
It runs the tests on the original model, then on the compliant reference handler
as a negative control (every defect must be NOT_REPRODUCED there).
"""
import json
import sys

try:
    from candidate import reference_policy as ref
    from candidate import test_helpers as th
except ImportError:  # executed as a script from candidate/
    import reference_policy as ref
    import test_helpers as th


# --------------------------------------------------------------------------- witnesses
def witness(name):
    """('S1/C1' -> supplied case) or ('W12' -> scenario): returns (offer_caps, actions)."""
    if name.startswith("S1/"):
        corpus = th.load_input("sequences-one.json")
        case = next(c for c in corpus["cases"] if c["id"] == name[3:])
        return corpus["offer_caps"], case["actions"]
    data = json.loads((th.ROOT / "candidate" / "scenarios.json").read_text(encoding="utf-8"))
    scenario = next(s for s in data["scenarios"] if s["id"] == name)
    return scenario["offer_caps"], scenario["actions"]


def execute(handler, name):
    caps, actions = witness(name)
    run = th.run_sequence(handler, th.load_input("state.json"), caps, actions)
    return {step["id"]: step for step in run["steps"]}


# --------------------------------------------------------------------------- accessors
def resp(step):
    return step["response"] if isinstance(step["response"], dict) else {}


def code(step):
    return resp(step).get("code")


def debit(step, account):
    """Positive = the account lost units during this action."""
    return step["before"]["accounts"][account] - step["after"]["accounts"][account]


def evidence(steps):
    return " || ".join(f"{s['id']}: {s['response']!r} | {th.format_diff(s['changes'])}"
                       for s in steps.values())


# --------------------------------------------------------------------------- checks
# Each check: (steps) -> (defect_reproduced, policy_expectation, observation)
def d1_replay_redebits(s):
    a = s["A02"]
    ok = code(a) == "replay" and debit(a, "A") == 30
    return ok, "A02 replay with no state change (A stays 70)", f"A02 {code(a)}, A debited {debit(a, 'A')}"


def d1_exact_replays_redebit(s):
    a, b = s["W12.2"], s["W12.3"]
    ok = code(a) == code(b) == "replay" and debit(a, "A") == debit(b, "A") == 10
    return ok, "both replays leave A at 90", f"replays debited A {debit(a, 'A')} and {debit(b, 'A')} (A ends at {b['after']['accounts']['A']})"


def d2_conflict_c1(s):
    a = s["A03"]
    ok = code(a) == "replay" and debit(a, "A") == 30
    return ok, "conflict (payload 29 differs from 30), no mutation", f"A03 {code(a)}, A debited {debit(a, 'A')}"


def _d2(step_id):
    def check(s):
        a = s[step_id]
        ok = code(a) == "replay"
        return ok, "conflict, no mutation", f"{step_id} {code(a)}, state changes: {th.format_diff(a['changes'])}"
    return check


def d3_bool_true(s):
    a = s["A04"]
    ok = code(a) == "ok" and resp(a).get("amount") is True and debit(a, "A") == 1
    return ok, "invalid, no mutation", f"A04 {code(a)}, amount {resp(a).get('amount')!r}, A debited {debit(a, 'A')}, claims {a['after']['claims']}"


def d3_bool_false(s):
    a = s["W06.1"]
    ok = code(a) == "ok" and resp(a).get("amount") is False
    return ok, "invalid, no mutation", f"W06.1 {code(a)}, amount {resp(a).get('amount')!r}, claims {a['after']['claims']}"


def d3_negative(s):
    a = s["A05"]
    ok = code(a) == "ok" and debit(a, "A") == -5
    return ok, "invalid, no mutation", f"A05 {code(a)}, A balance {a['before']['accounts']['A']} -> {a['after']['accounts']['A']}"


def d3_zero_consumes_claim(s):
    a, b = s["W03.1"], s["W03.2"]
    consumed = a["after"]["claims"].get("A/spring") == 0
    ok = code(a) == "ok" and resp(a).get("amount") == 0 and consumed
    return (ok, "W03.1 invalid with no mutation; corrected retry W03.2 ok (A 95)",
            f"W03.1 {code(a)} amount 0, claim A/spring=0 recorded; retry W03.2 with 5 got {code(b)} amount {resp(b).get('amount')!r}")


def d4_insufficient_mutates(s):
    a = s["A06"]
    ok = code(a) == "insufficient" and "B/spring" in a["after"]["claims"] and "B/spring" not in a["before"]["claims"]
    return ok, "insufficient with the complete state unchanged", f"A06 {code(a)}, claims {a['before']['claims']} -> {a['after']['claims']}"


def _d4_retry(first, second):
    def check(s):
        a, b = s[first], s[second]
        ok = code(a) == "insufficient" and code(b) == "claimed"
        return ok, f"{first} insufficient; corrected retry {second} ok", f"{first} {code(a)}, then {second} {code(b)}"
    return check


def d5_validation_order(s):
    a = s["W09.1"]
    ok = code(a) == "missing" and not a["changes"]
    return ok, "invalid (amount validated before identity)", f"W09.1 {code(a)}"


def d6_cross_account_debit(s):
    a = s["W14.2"]
    ok = code(a) == "replay" and debit(a, "A") == 10 and debit(a, "B") == 0
    return ok, "conflict; neither account touched", f"B's request got {code(a)}; A debited {debit(a, 'A')}, B debited {debit(a, 'B')}"


def d7_replays_drive_balance_negative(s):
    balances = [step["after"]["accounts"]["A"] for step in s.values()]
    ok = min(balances) < 0
    return ok, "A stays at 70 after every action", f"A after each action: {balances}"


CHECKS = [
    # id, CR rule, description, witness, check
    ("D1-S1-C1", "CR5", "replay response is charged again", "S1/C1", d1_replay_redebits),
    ("D1-W12", "CR5", "exact replays are charged again", "W12", d1_exact_replays_redebit),
    ("D2-S1-C1", "CR5", "same id, different amount is replayed, not a conflict", "S1/C1", d2_conflict_c1),
    ("D2-W13", "CR5", "same id, different amount is replayed, not a conflict", "W13", _d2("W13.2")),
    ("D2-W14", "CR5", "same id, different account is replayed, not a conflict", "W14", _d2("W14.2")),
    ("D2-W15", "CR5", "same id, different offer is replayed, not a conflict", "W15", _d2("W15.2")),
    ("D2-W16", "CR5", "same id, True instead of 1 is replayed, not a conflict", "W16", _d2("W16.2")),
    ("D3-S1-C2", "CR2", "bool True accepted as amount", "S1/C2", d3_bool_true),
    ("D3-W06", "CR2", "bool False accepted as amount", "W06", d3_bool_false),
    ("D3-S1-C3", "CR2", "negative amount accepted and credited", "S1/C3", d3_negative),
    ("D3-W03", "CR2", "zero amount accepted and consumes the claim", "W03", d3_zero_consumes_claim),
    ("D4-S1-C4", "CR4", "insufficient denial writes a claim", "S1/C4", d4_insufficient_mutates),
    ("D4-W17", "CR4", "corrected retry (same id) blocked after insufficient", "W17", _d4_retry("W17.1", "W17.2")),
    ("D4-W18", "CR4", "corrected retry (new id) blocked after insufficient", "W18", _d4_retry("W18.1", "W18.2")),
    ("D5-W09", "CR1", "negative amount for unknown account returns missing", "W09", d5_validation_order),
    ("D6-W14", "CR5", "another account's request id debits the original account", "W14", d6_cross_account_debit),
    ("D7-W19", "CR6", "repeated replays push a balance below zero", "W19", d7_replays_drive_balance_negative),
]


def run_defect_tests(handler):
    results = []
    for check_id, rule, description, name, check in CHECKS:
        try:
            steps = execute(handler, name)
            ok, expected, actual = check(steps)
            results.append(th.make_result(check_id, "defect", rule, description, ok, expected, actual, evidence(steps)))
        except Exception as exc:  # a checker problem, never reported as a model defect
            results.append(th.error_result(check_id, "defect", rule, description, f"{type(exc).__name__}: {exc}"))
    return results


def tally(results):
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


def main():
    model = th.load_model()
    print(f"Python {sys.version.split()[0]} | witnesses: S1 cases and candidate/scenarios.json")
    print("== Defect characterization on the ORIGINAL model (inputs/credit_model.py)")
    results = run_defect_tests(model.redeem)
    for r in results:
        print(th.format_result(dict(r, detail="")))
        print(f"      evidence: {r['detail']}")
    print("model:", tally(results))

    print("== Negative control on the compliant reference handler (every defect must be NOT_REPRODUCED)")
    control = run_defect_tests(ref.redeem_reference)
    for r in control:
        print(f"[{r['status']}] {r['id']}" + (f" | {r['detail']}" if r["status"] == th.ERROR else ""))
    print("control:", tally(control))

    healthy = (all(r["status"] == th.CONFIRMED for r in results)
               and all(r["status"] == th.NOT_REPRODUCED for r in control))
    print("RESULT:", "all defects reproduced on the model and none on the control" if healthy
          else "UNEXPECTED: investigate (a defect not reproduced, a control failure, or an execution error)")
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())