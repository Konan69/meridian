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

Meridian work loop:

- Start by reading `docs/simulation-architecture.md` and, for payload or UI stream changes, `docs/simulation-payload-contract.md`.
- Pick the next change that makes the economy more believable: agent behavior, merchant adoption, route pressure, treasury effects, trust/memory, reports, or UI explanation.
- Prefer small, complete edits that include the matching test, doc, or frontend normalization update in the same pass.
- After a safe edit, run the narrowest relevant check first, then the whole-app gate when the change could affect contracts.
- If a reference repo under `ref/` suggests useful behavior, adapt the idea into Meridian's payment-economy model instead of copying its source or shifting the app toward that repo's domain.
- When a phase feels done, choose the next useful repo-backed step yourself. Do not ask the user what phase comes next.
