"""Deliberately vulnerable training model; no server or network."""
import copy
import json
import pathlib
import sys


def redeem(state, action):
    rid = action["request_id"]
    account, offer, amount = (action[k] for k in ("account", "offer", "amount"))
    if rid in state["requests"]:
        old = state["requests"][rid]
        state["accounts"][old["payload"][0]] -= old["response"]["amount"]
        return {"code": "replay", "amount": old["response"]["amount"]}
    if not isinstance(amount, int):
        return {"code": "invalid"}
    if account not in state["accounts"] or offer not in state["offers"]:
        return {"code": "missing"}
    rule = state["offers"][offer]
    if account not in rule["eligible"]:
        return {"code": "ineligible"}
    if amount > rule["cap"]:
        return {"code": "cap"}
    claim = account + "/" + offer
    if claim in state["claims"]:
        return {"code": "claimed"}
    state["claims"][claim] = amount
    if state["accounts"][account] < amount:
        return {"code": "insufficient"}
    state["accounts"][account] -= amount
    result = {"code": "ok", "amount": amount}
    state["requests"][rid] = {"payload": [account, offer, amount], "response": result}
    return result


def replay(initial, corpus, handler=redeem):
    cases = []
    for case in corpus["cases"]:
        state = copy.deepcopy(initial)
        for offer, cap in corpus["offer_caps"].items():
            state["offers"][offer]["cap"] = cap
        steps = []
        for action in case["actions"]:
            before = copy.deepcopy(state)
            response = handler(state, action)
            steps.append({"id": action["id"], "before": before,
                          "response": response, "after": copy.deepcopy(state)})
        cases.append({"id": case["id"], "steps": steps, "final": state})
    return cases


if __name__ == "__main__":
    initial = json.loads(pathlib.Path(__file__).with_name("state.json").read_text())
    corpus = json.loads(pathlib.Path(sys.argv[1]).read_text())
    print(json.dumps(replay(initial, corpus), sort_keys=True))
