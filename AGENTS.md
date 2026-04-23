# AGENTS.md

Session rules:

- Favor concision over perfect grammar when meaning stays clear.
- Use `python3`, never bare `python`.
- If the next action is non-destructive and naturally follows from the user's request, do it proactively.
- Keep moving through safe next steps until the task is done or a real blocker is hit.
- Do not ask what the next phase is. Infer the next useful phase from repo state, user intent, and previous work, then proceed.
- Do not stop for approval before safe exploration, local reference cloning, benchmark runs, tests, or scoped code edits.
- Meridian is a simulation of agents using different payment protocols to initiate transactions inside an evolving economy. Treat live protocol integrations as reference rails and constraints for the simulation, not as the product's primary purpose.
- Use `ref/` for local reference checkouts such as MiroFish and protocol dependency repos. Reference code is for study and adaptation; do not vendor it into Meridian unless explicitly needed.

Meridian product contract:

- The main system is the simulated economy: autonomous buyer agents, merchants, payment protocols, settlement routes, treasury posture, trust, memory, and rail P&L.
- Protocol integrations exist to make the simulation realistic. Do not recast Meridian as a wallet, payment gateway, funding dashboard, or SDK demo.
- Every product-facing change should help agents initiate transactions, compare protocol outcomes, or visualize the ecosystem economy through graph, timeline, reports, and chat.

Meridian work loop:

- Start by reading `docs/simulation-architecture.md` and, for payload or UI stream changes, `docs/simulation-payload-contract.md`.
- Pick the next change that makes the economy more believable: agent behavior, merchant adoption, route pressure, treasury effects, trust/memory, reports, or UI explanation.
- Prefer small, complete edits that include the matching test, doc, or frontend normalization update in the same pass.
- After a safe edit, run the narrowest relevant check first, then the whole-app gate when the change could affect contracts.
- Before committing or combining an Evo checkpoint, run `evo gate list <parent-or-checkpoint>` and preserve every focused gate along with `whole_app_contract_gate`. Manual diff combines do not automatically carry gate metadata; current focused protocol gates include `ap2_offline_settlement_semantics`, `stripe_mpp_offline_semantics`, `atxp_offline_direct_transfer_topup_contract`, and `cdp_offline_treasury_transfer_contract`. `benchmark_whole_app.py --list-tasks` also prints machine-readable gate guidance tied to the related task ids.
- Budget duplicate focused gate validation as intentional correctness cost. The full benchmark runs `service_offline_protocol_tests`, then inherited focused gates may rerun `service_offline_ap2`, `service_offline_stripe`, `service_offline_atxp`, or `service_offline_cdp`; do not remove, skip, merge, or weaken those gates to save time.
- If a reference repo under `ref/` suggests useful behavior, adapt the idea into Meridian's payment-economy model instead of copying its source or shifting the app toward that repo's domain.
- When a phase feels done, choose the next useful repo-backed step yourself. Do not ask the user what phase comes next, and do not pause for phase approval unless the next action is destructive or blocked.
