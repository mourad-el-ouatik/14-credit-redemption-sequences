"""Phase 5: policy-compliance assertions (stdlib only).

Unlike defect_tests.py (is this known defect reproduced?), these ask whether the
handler SATISFIES the policy. A violation is reported as FAIL and is never hidden.

Every step is judged against ITS OWN actual `before` state, so a defect early in a
sequence does not make later, correct steps fail by cascade. Families:

  CR1-response   response (code and amount) equals what the policy requires        [every step]
  CR2-amount     no invalid amount is accepted (exact int, not bool, > 0, <= cap)  [fresh request ids]
  CR3-success    where the policy requires a success: exact transition (one debit, one claim, one request)
  CR4-denial     where the policy requires a denial: the ENTIRE state is unchanged
  CR5-replay     a reused successful id gives replay/conflict with no mutation      [reused ids]
  CR6-invariants conservation, non-negative balances, claim<->request bijection, offers intact [every step]
  EXP-scenario   response and complete state equal the hand-written expectation    [W scenarios only]

CR3/CR4/CR5 apply according to what the policy requires for the step's actual `before`
state, not according to the handler's answer. One result per (family, sequence),
emitted only if the family applies to at least one step of that sequence.

Run:  python -B candidate/policy_checks.py [--all]
Runs on the original model (violations expected and shown), then on the compliant
reference handler as a control (every check must PASS).
"""
import copy
import json
import sys

try:
    from candidate import reference_policy as ref
    from candidate import test_helpers as th
except ImportError:  # executed as a script from candidate/
    import reference_policy as ref
    import test_helpers as th

DENIALS = ("invalid", "missing", "ineligible", "cap", "claimed", "insufficient")

FAMILIES = [
    ("CR1-response", "CR1", "response matches the policy decision order"),
    ("CR2-amount", "CR2", "accepted amounts are exact positive ints within the cap"),
    ("CR3-success", "CR3", "success debits only the account and records one claim and one request"),
    ("CR4-denial", "CR4", "denials leave the entire state unchanged"),
    ("CR5-replay", "CR5", "reused successful ids give replay/conflict without mutation"),
    ("CR6-invariants", "CR6", "balances, claims, requests and offers stay consistent"),
    ("EXP-scenario", "EXP", "response and full state equal the policy-derived expectation"),
]


# --------------------------------------------------------------------------- sequences
def snapshot_sequences(filename, label):
    corpus = th.load_input(filename)
    return [{"id": f"{label}/{case['id']}", "offer_caps": corpus["offer_caps"], "actions": case["actions"],
             "expected": None} for case in corpus["cases"]]


def scenario_sequences():
    data = json.loads((th.ROOT / "candidate" / "scenarios.json").read_text(encoding="utf-8"))
    return [{"id": s["id"], "offer_caps": s["offer_caps"], "actions": s["actions"], "expected": s["expected"],
             "rules": ",".join(s["rules"])} for s in data["scenarios"]]


# --------------------------------------------------------------------------- per-step verdicts
def _code(response):
    return response.get("code") if isinstance(response, dict) else None


def _expected_after_success(before, action):
    after = copy.deepcopy(before)
    account, offer, amount = action["account"], action["offer"], action["amount"]
    after["accounts"][account] -= amount
    after["claims"][f"{account}/{offer}"] = amount
    after["requests"][action["request_id"]] = {"payload": [account, offer, amount],
                                               "response": {"code": "ok", "amount": amount}}
    return after


def step_verdicts(step, start):
    """-> {family: (ok, detail)} for the families that apply to this step."""
    before, after, action, response = step["before"], step["after"], step["action"], step["response"]
    code = _code(response)
    out = {}

    expected = ref.policy_response(before, action)
    bad = th.diff_state(expected, response)
    out["CR1-response"] = (not bad, "" if not bad else f"policy requires {expected!r}, got {response!r}")

    # Applicability follows what the POLICY requires for this step's actual `before`
    # state, never the handler's answer, so a wrongly accepted request cannot dodge a family.
    if action["request_id"] not in before["requests"]:  # CR2 applies to fresh ids only (replay lookup comes first)
        amount = action["amount"]
        cap = before["offers"].get(action["offer"], {}).get("cap")
        valid = type(amount) is int and amount > 0 and cap is not None and amount <= cap
        accepted_invalid = code == "ok" and not valid
        out["CR2-amount"] = (not accepted_invalid,
                             f"accepted amount {amount!r} (type {type(amount).__name__}), cap {cap}" if accepted_invalid else "")

    if expected["code"] == "ok":  # the policy requires a success: its transition must be exact
        try:
            diffs = th.diff_state(_expected_after_success(before, action), after)
            why = []
            if bad:
                why.append(f"response {response!r}, policy requires {expected!r}")
            if diffs:
                why.append(f"transition differs from CR3: {th.format_diff(diffs)}")
            out["CR3-success"] = (not why, "; ".join(why))
        except Exception as exc:
            out["CR3-success"] = (False, f"cannot build expected transition: {type(exc).__name__}: {exc}")

    if expected["code"] in DENIALS:  # the policy requires a denial: nothing may change
        out["CR4-denial"] = (not step["changes"],
                             "" if not step["changes"] else f"policy requires {expected['code']}, got {code}; state mutated: {th.format_diff(step['changes'])}")

    if action["request_id"] in before["requests"]:
        ok = not bad and not step["changes"]
        why = []
        if bad:
            why.append(f"policy requires {expected!r}, got {response!r}")
        if step["changes"]:
            why.append(f"mutated state: {th.format_diff(step['changes'])}")
        out["CR5-replay"] = (ok, "; ".join(why))

    violations = th.invariant_violations(start, after)
    out["CR6-invariants"] = (not violations, "; ".join(violations))
    return out


def _exp_verdicts(run, expected_steps):
    """Sequence-level: compare to absolute hand-written expectations."""
    verdicts, expected_state = [], copy.deepcopy(run["start"])
    for step, exp in zip(run["steps"], expected_steps):
        if exp["state"] != "unchanged":
            for key in ("accounts", "claims", "requests"):
                expected_state[key] = exp["state"][key]
        why = []
        if th.diff_state(exp["response"], step["response"]):
            why.append(f"response {step['response']!r}, expected {exp['response']!r}")
        state_diff = th.diff_state(expected_state, step["after"])
        if state_diff:
            why.append(f"state differs: {th.format_diff(state_diff)}")
        verdicts.append((step["id"], not why, "; ".join(why)))
    return verdicts


# --------------------------------------------------------------------------- runner
def run_policy_checks(handler, sequences):
    initial = th.load_input("state.json")
    results = []
    for seq in sequences:
        try:
            run = th.run_sequence(handler, initial, seq["offer_caps"], seq["actions"])
            per_family = {name: [] for name, _, _ in FAMILIES}
            for step in run["steps"]:
                if step["exception"]:
                    raise RuntimeError(f"model raised on {step['id']}: {step['exception']}")
                for family, (ok, detail) in step_verdicts(step, run["start"]).items():
                    per_family[family].append((step["id"], ok, detail))
            if seq["expected"] is not None:
                per_family["EXP-scenario"] = _exp_verdicts(run, seq["expected"])
            for family, rule, description in FAMILIES:
                verdicts = per_family[family]
                if not verdicts:
                    continue
                failing = [(sid, detail) for sid, ok, detail in verdicts if not ok]
                results.append(th.make_result(
                    f"{family}/{seq['id']}", "policy", seq.get("rules", rule) if family == "EXP-scenario" else rule,
                    description, not failing,
                    f"all {len(verdicts)} applicable step(s) conform",
                    "conforms" if not failing else f"{len(failing)} of {len(verdicts)} violate: {', '.join(s for s, _ in failing)}",
                    "; ".join(f"{sid}: {detail}" for sid, detail in failing)))
        except Exception as exc:  # checker/input problem: never reported as a model violation
            results.append(th.error_result(f"POLICY/{seq['id']}", "policy", "-", "sequence could not be checked",
                                           f"{type(exc).__name__}: {exc}"))
    return results


def tally(results):
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


def by_family(results):
    table = {}
    for r in results:
        family = r["id"].split("/", 1)[0]
        table.setdefault(family, {}).setdefault(r["status"], 0)
        table[family][r["status"]] += 1
    return table


# Injected defects on top of the compliant reference: each must trip EXACTLY the families
# listed, proving the families are distinct and none is vacuous.
def _mut_replay_redebits(state, action):
    response = ref.redeem_reference(state, action)
    if response["code"] == "replay":
        state["accounts"][state["requests"][action["request_id"]]["payload"][0]] -= response["amount"]
    return response


def _mut_insufficient_writes_claim(state, action):
    response = ref.redeem_reference(state, action)
    if response["code"] == "insufficient":
        state["claims"][f"{action['account']}/{action['offer']}"] = action["amount"]
    return response


def _mut_conflict_reported_as_replay(state, action):
    response = ref.redeem_reference(state, action)
    if response["code"] == "conflict":
        return {"code": "replay", "amount": state["requests"][action["request_id"]]["response"]["amount"]}
    return response


MUTANTS = [
    ("replay re-debits the original account", _mut_replay_redebits,
     {"CR5-replay", "CR6-invariants", "EXP-scenario"}),
    ("insufficient denial writes the claim", _mut_insufficient_writes_claim,
     {"CR4-denial", "CR6-invariants", "EXP-scenario"}),
    ("conflict reported as replay (no mutation)", _mut_conflict_reported_as_replay,
     {"CR1-response", "CR5-replay", "EXP-scenario"}),
]


def discrimination_check(sequences):
    rows = []
    for name, handler, expected in MUTANTS:
        results = run_policy_checks(handler, sequences)
        failing = {r["id"].split("/", 1)[0] for r in results if r["status"] == th.FAIL}
        errored = any(r["status"] == th.ERROR for r in results)
        rows.append((name, expected, failing, failing == expected and not errored))
    return rows


def main():
    show_all = "--all" in sys.argv
    sequences = snapshot_sequences("sequences-one.json", "S1") + scenario_sequences()
    print(f"Python {sys.version.split()[0]} | {len(sequences)} sequences (6 S1 cases + 21 W scenarios)")

    print("== Policy compliance of the ORIGINAL model (inputs/credit_model.py)")
    results = run_policy_checks(th.load_model().redeem, sequences)
    for r in results:
        if show_all or r["status"] != th.PASS:
            print(th.format_result(r))
    print("by family:")
    for family, counts in by_family(results).items():
        print(f"  {family:15} {counts}")
    print("model:", tally(results))

    print("== Control: compliant reference handler (every check must PASS)")
    control = run_policy_checks(ref.redeem_reference, sequences)
    for r in control:
        if r["status"] != th.PASS:
            print(th.format_result(r))
    print("control:", tally(control))

    print("== Discrimination: each injected defect must trip exactly the expected families")
    rows = discrimination_check(sequences)
    for name, expected, failing, ok in rows:
        print(f"[{'OK' if ok else 'MISMATCH'}] {name}: tripped {sorted(failing)}" + ("" if ok else f", expected {sorted(expected)}"))

    clean = (all(r["status"] == th.PASS for r in control)
             and not any(r["status"] == th.ERROR for r in results)
             and all(ok for *_, ok in rows))
    print("RESULT:", "control passes everything, injected defects are caught by the right families; model violations above are real findings"
          if clean else "UNEXPECTED: the control failed, a check errored or a family did not discriminate; investigate the checker")
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())