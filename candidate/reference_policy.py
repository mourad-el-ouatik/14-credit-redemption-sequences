"""Policy-compliant reference handler, used ONLY as a negative control (stdlib only).

Written from the text of inputs/credit-policy.md (CR1-CR5), without copying the
supplied model. It is NOT a proposed fix for the model under audit: it exists so
the checkers can be shown to (a) pass a compliant implementation and (b) report
defects on the vulnerable one. Same signature as credit_model.redeem.
"""


def _same(x, y):
    """Exact typed equality: bool differs from int (True == 1 in Python)."""
    return type(x) is type(y) and x == y


def redeem_reference(state, action):
    rid, account, offer, amount = (action[k] for k in ("request_id", "account", "offer", "amount"))

    # CR1/CR5: successful request-id lookup comes first; it never mutates.
    if rid in state["requests"]:
        record = state["requests"][rid]
        same = all(_same(old, new) for old, new in zip(record["payload"], [account, offer, amount]))
        if same:
            return {"code": "replay", "amount": record["response"]["amount"]}
        return {"code": "conflict"}

    # CR2: exact int (not bool), positive.
    if type(amount) is not int or amount <= 0:
        return {"code": "invalid"}
    if account not in state["accounts"] or offer not in state["offers"]:
        return {"code": "missing"}
    rule = state["offers"][offer]
    if account not in rule["eligible"]:
        return {"code": "ineligible"}
    if amount > rule["cap"]:
        return {"code": "cap"}
    claim = f"{account}/{offer}"
    if claim in state["claims"]:
        return {"code": "claimed"}
    if state["accounts"][account] < amount:
        return {"code": "insufficient"}

    # CR3/CR5: mutate only on success.
    state["accounts"][account] -= amount
    state["claims"][claim] = amount
    result = {"code": "ok", "amount": amount}
    state["requests"][rid] = {"payload": [account, offer, amount], "response": result}
    return result