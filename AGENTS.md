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
