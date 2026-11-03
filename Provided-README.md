# Assess credit redemption sequences

The fictional WillowPass team manages promotional credits. Ordinary single requests look correct, but a teammate wants evidence that ordered redemption sequences preserve balances, eligibility and request replay rules. Help engineering decide what to fix first. These are synthetic noncash promotional units, never real payments.

**Deliberately vulnerable training code:** the supplied Python model runs entirely in memory, has no threads, and makes no network calls. Assess sequential behavior only; this cannot demonstrate a concurrent race or a production payment exploit.

## Inputs and setup

- [Model and replay CLI](inputs/credit_model.py): preserve this original for evidence; optional repairs belong in a copy.
- [Initial accounts and offers](inputs/state.json): fresh state for each case.
- [Credit policy](inputs/credit-policy.md): CR1–CR6 define exact response and state rules.
- [First sequences](inputs/sequences-one.json): S1 case/action IDs and cap override.
- [Second snapshot](inputs/sequences-two.json): S2 changes business-rule data, using the same schema.
- [Teammate notes](inputs/teammate-notes.md): three claims to assess, not authoritative facts.

Baseline skills: read short Python dictionaries/functions, understand request IDs and write assertions. Python 3.10+ standard library only; no installation, account, service or paid tool is needed. From exported `candidate/`, run:

```sh
python3 -B inputs/credit_model.py inputs/sequences-one.json
python3 -B inputs/credit_model.py inputs/sequences-two.json
```

Each exits 0 and prints JSON, including full before/after state for every action. Both corpora contain six independent cases and ten actions. `replay(initial, corpus, handler)` and `redeem(state, action)` can be imported into your runner. Never share mutable state across independent cases.

## Core work and acceptance

1. Build a reusable offline sequence runner/checker from CR1–CR6. Execute the actual original model; assert every response and full state transition, including all account balances, claims, successful request records and unchanged offers. Separate assertions that characterize observed defects from assertions of desired policy. Report failures visibly; do not silently treat a broken policy as passing.
2. Extend the corpus with legitimate and adversarial controls: exact cap, zero/negative/bool amounts, repeat redemption under a new ID, exact replay, conflicting ID reuse, and denied request followed by corrected valid retry. Verify fresh resets, conservation of promotional units, no denial mutation and no replay mutation. Do not rely on statuses alone.
3. Confirm or refute N1–N3 with preconditions, case/action IDs, exact commands, actual responses/state and bounded impact. Provide prioritized engineering-ready findings with policy/code references, root cause, minimal recommendation, legitimate control and next verification step. Group shared causes where useful.
4. Run the same checker unchanged on S2; reconcile changed and unchanged actions. Record any refinement, then rerun S1. Submit captured evidence and a concise handoff; repairing the model is optional and earns no separate marks. Full marks require a working assessment, not a production redesign.

Acceptance: another intern can reproduce your evidence with one documented command, distinguish expected vulnerable behavior from policy compliance, and see both snapshots checked without changing rules. Preserve supplied evidence; add tests in your own files. Do not claim concurrency, authentication or external payment guarantees.

## Submission, AI and timing

Submit an archive or repository containing runnable artifacts, source/evidence references, captured verification output and a concise walkthrough (up to five minutes recording **or equivalent accessible text**). Include exact commands and tool versions. Add a short decision/work log recording prioritization, one obstacle and response, one validation/refinement, limits and next step. Add an AI-use note with one accepted, corrected or rejected output and how you checked it; if no AI was used, say so. Never fabricate an AI failure.

No AI tool is provided: you may use any AI tool you already have. AI is allowed and encouraged for coding, drafting, research, automation and critique. Verify AI output. Tool choice is not graded; free/offline tools are supported, no purchases or personal account access are needed. Synthetic fixtures are the authoritative universe; outside research is optional and cannot affect marks.

Your 24 hours start when you click **Start** on the link in your invitation email; the exercise zip becomes available at that moment. Send your submission back within 24 hours of clicking Start. You are not expected to work for the full 24 hours: organize your own working time and breaks within the window. There are no surprise messages or overnight availability requirements, and hours worked are not scored. The clock tests bounded execution, follow-through and verification, not willingness to sacrifice sleep. Do only this assigned exercise. Full marks are possible on core alone: usable result **40**, accuracy/verification **25**, prioritization **20**, communication/handoff **15**. No AI-detector, writing-volume or prose-polish scoring. Work is an exercise submission, not a company deliverable: no external targets, outreach, production actions or public deployment.
