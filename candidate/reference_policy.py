"""Policy-compliant reference, used ONLY as a negative control and policy oracle (stdlib only).

Written from the text of inputs/credit-policy.md (CR1-CR5), without copying the
supplied model. It is NOT a proposed fix for the model under audit.

- policy_response(state, action): PURE decision function. Returns the response the
  policy requires for `action` on `state` (CR1 order, CR2 amount rules, CR5 replay
  and conflict). It never mutates anything.
- redeem_reference(state, action): same signature as credit_model.redeem; applies
  CR3 on success only. Lets the checkers be shown to pass a compliant handler.

policy_response is validated independently by the hand-written expectations in
candidate/scenarios.json (see policy_checks.py, family EXP-scenario).
"""


def _same(x, y):
    """Exact typed equality: bool differs from int (True == 1 in Python)."""
    return type(x) is type(y) and x == y


def policy_response(state, action):
    rid, account, offer, amount = (action[k] for k in ("request_id", "account", "offer", "amount"))

    # CR1/CR5: successful request-id lookup comes first; it never mutates.
    if rid in state["requests"]:
        record = state["requests"][rid]
        same = all(_same(old, new) for old, new in zip(record["payload"], [account, offer, amount]))
        if same:
            return {"code": "replay", "amount": record["response"]["amount"]}
        return {"code": "conflict"}

    # CR2: exact int (not bool) and positive.
    if type(amount) is not int or amount <= 0:
        return {"code": "invalid"}
    if account not in state["accounts"] or offer not in state["offers"]:
        return {"code": "missing"}
    rule = state["offers"][offer]
    if account not in rule["eligible"]:
        return {"code": "ineligible"}
    if amount > rule["cap"]:
        return {"code": "cap"}
    if f"{account}/{offer}" in state["claims"]:
        return {"code": "claimed"}
    if state["accounts"][account] < amount:
        return {"code": "insufficient"}
    return {"code": "ok", "amount": amount}


def redeem_reference(state, action):
    response = policy_response(state, action)
    if response["code"] != "ok":
        return response  # CR4/CR5: every non-success leaves the state untouched

    # CR3/CR5: mutate only on success.
    account, offer, amount = action["account"], action["offer"], action["amount"]
    state["accounts"][account] -= amount
    state["claims"][f"{account}/{offer}"] = amount
    state["requests"][action["request_id"]] = {"payload": [account, offer, amount], "response": response}
    return response