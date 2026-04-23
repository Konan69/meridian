# Meridian Simulation Architecture

Meridian models an economy of agents choosing between payment protocols. Live
rails are constraints and calibration points; the product surface is the
simulation: agents, merchants, stablecoin domains, routes, protocol trust,
treasury pressure, and emergent adoption.

## Product Contract

Meridian is a simulation of agents initiating transactions across payment
protocols and settlement routes. The core job is to make the ecosystem economy
legible: who bought what, which protocol moved the value, how route pressure and
treasury posture changed, and why agents or merchants changed trust.

Live CDP, Stripe, ATXP, AP2, x402, and related integrations are reference rails
for realism. They should constrain fees, readiness, latency, failures, balances,
and settlement vocabulary, but they are not the product center. Product-facing
work should keep the graph, timeline, reports, and chat focused on the simulated
economy rather than turning Meridian into an SDK console or funding dashboard.

The workbench economy observability surface is part of that contract. Route
ledger, rail P&L, and merchant-switch evidence should stay tied to simulation
store state and payload fields, not drift into provider diagnostics.

## Reference Checkouts

Local references live under `ref/` and are ignored by git.

- `ref/mirofish`: multi-agent simulation workflow reference.
- `ref/deps/*`: protocol and simulation dependency references cloned for local
  inspection, currently AP2, ATXP SDK/CLI, x402, CDP SDK, MPPX, Stripe Node,
  OASIS, and CAMEL.

MiroFish patterns adapted into Meridian:

- Seeded world: a scenario prompt becomes a named economy seed.
- Graph scaffold: entities and relationships are visible before simulation.
- Agent personas: agents carry budgets, preferences, trust, and memory.
- Action stream: each round emits transaction, route, trust, and world events.
- Deep interaction: reports and chat are grounded in the simulation trace.

Reference use rules:

- Borrow workflow shape from `ref/mirofish`, not its domain assumptions.
- Use protocol repos under `ref/deps/*` for settlement vocabulary, latency,
  fee, failure, and readiness constraints.
- Use OASIS and CAMEL as multi-agent economy references for role design,
  interaction loops, and evaluation ideas.
- Do not vendor reference source into Meridian unless a future task explicitly
  needs a small, attributed adaptation.

## Economy Loop

Each simulation round:

1. Selects active buyer agents from remaining budgets.
2. Chooses market opportunities and workload type.
3. Scores feasible payment options across supported protocols and settlement
   routes.
4. Executes the transaction through the engine-facing protocol adapter.
5. Updates balances, route pressure, rail economics, merchant reputation, and
   agent protocol trust.
6. Emits agent memory and world events for visualization and reporting.
7. Lets merchants and agents shift protocol preference based on observed
   economics and accumulated trust.

## Route-Score Rationale

Route score is the bridge between one agent transaction and the protocol
economy that grows around it. A buyer does not just pick the cheapest live rail;
the score weighs fees, latency, reliability, route pressure, treasury fit, trust,
and a self-sustainability bias. That makes protocol choice evidence, not a
provider demo result.

Keep the named route-score fields visible in payloads and docs:
`route_score`, `route_score_drivers`, `route_score_context`,
`avg_route_score`, `avg_route_pressure_penalty`, `avg_sustainability_bias`,
`route_score_pressure_drag`, and `route_score_sustainability_lift`. Buyer
choices expose the first three fields; protocol summaries aggregate the next
three; merchant switch reports use pressure drag and sustainability lift when
route evidence changes adoption. Together they explain self-sustainable
protocol evolution: protocols gain or lose usage because simulated merchants
and agents see route capacity, treasury posture, margin, and trust changing.

## Stream Contract

The simulation API streams NDJSON. Important event types:

- `setup`: initial world size, supported protocols, seed metadata.
- `simulation_start`: world identity and configured flow mix.
- `purchase`: settled buyer transaction.
- `purchase_failed`: failed buyer transaction.
- `agent_memory`: per-agent protocol trust update.
- `trust_snapshot`: aggregate trust summary by protocol.
- `world_event`: simulation-level narrative event.
- `route_pressure`: round-level route capacity pressure, mirrored as
  `world_event` data for economy analysis.
- `treasury_rebalance`: merchant treasury recycling between settlement domains,
  also mirrored as `world_event` data.
- `treasury_posture`: merchant preferred-domain shortfall and rebalance
  readiness, mirrored as `world_event` data.
- `merchant_switch`: merchant protocol adoption/removal.
- `agent_preference_shift`: agent preference changed from memory.
- `simulation_complete`: final summaries, balances, memory log, world events.

For field-level payload details, frontend normalization helpers, and the
MiroFish adaptation boundary, see `docs/simulation-payload-contract.md`.

## Autonomous Checkpoints

When an Evo checkpoint is already at benchmark score `1.0`, treat it as the
contract baseline to preserve. Useful autonomous changes should make the
economy more believable, the workbench explanation clearer, or future
regression diagnosis easier; they should not relax static contracts, compile
checks, or build/test commands.

Current protected surfaces checkpoint:

- `static_contracts` / `whole_app_contract_gate`: static runtime, funding,
  trace metadata, docs, and Python compile contracts. Validate with
  `evo gate list <checkpoint>` and
  `python3 benchmark_whole_app.py --target . --profile gate --min-score 1.0`.
- `service_offline_protocol_tests`: aggregate CDP, Stripe MPP, ATXP, and AP2
  credential-free helper semantics. Validate with
  `python3 benchmark_whole_app.py --target . --profile benchmark --task-id service_offline_protocol_tests`
  or inspect `benchmark_whole_app.py --list-tasks` for component task ids.
- Focused service gates: `cdp_offline_treasury_transfer_contract`,
  `stripe_mpp_offline_semantics`,
  `atxp_offline_direct_transfer_topup_contract`, and
  `ap2_offline_settlement_semantics`. Validate by preserving the exact commands
  from `evo gate list <checkpoint>`; these intentionally rerun part of the
  aggregate service suite.
- `route_score_merchant_switch_report_readout`: report wording must explain
  route-score-driven merchant protocol switches. Validate with the inherited
  gate from `evo gate list <checkpoint>` or the focused pytest named there.

Benchmark traces are part of the handoff between workers. Keep command context,
cache key inputs, and static contract coverage visible so the next worker can
separate a real validation failure from cache setup or timing variance.
For build and test tasks, read `trace_metadata.execution.score_policy` first:
return code decides correctness, while elapsed time only contributes the small
speed bonus. Cache metadata explains dependency reuse; validation metadata lists
the install, check, build, compile, or test phases that still ran.
For `static_contracts`, use `trace_metadata.validation.coverage_areas` before
editing a needle. The areas explain whether a string protects local startup,
funding guidance, ATXP settlement, frontend navigation, or engine capability
readiness.
For synthetic summary tasks such as `service_builds_summary`, inspect
`trace_metadata.aggregation.component_tasks`; the summary is only an average,
and the component task traces show the real commands and caches.
For local validation, `benchmark_whole_app.py --list-tasks` prints every valid
task id and marks the default benchmark and gate profile members. Explicit task
selection accepts `--task-id web_check_build` repeatedly, or
`--task-ids service_offline_cdp,web_check_build`. Selection is opt-in; the
default `--profile benchmark` and `--profile gate` task lists still run their
normal coverage, and selected tasks still execute their real install, build,
test, or compile commands.
The same output includes `metadata_schema` with
`kind: list_tasks_metadata_schema`. Treat it as the schema for listing metadata:
`schema_version: 1` identifies the current schema contract;
`task_entry_required_keys` covers `task_id`, `benchmark_profile`, and
`gate_profile`; `task_entry_optional_keys` covers diagnostic fields such as
`manual_validation_task_ids`, `duplicate_validation`, `semantic_surfaces`, and
`preserved_gate_names`. Static contracts compare the live task catalog with
that schema and require this docs anchor and version, so adding a new listing
field or changing schema meaning means updating the schema, version, and docs
in the same change.
For pnpm build tasks, `trace_metadata.cache.node_modules_seed` reports whether
the benchmark hardlinked a compatible `node_modules` tree from another Evo
worktree before running the frozen install.
Service TypeScript build traces also list manual phase tasks under
`trace_metadata.validation.manual_phase_tasks`. Use `service_cdp_install`,
`service_cdp_build`, `service_stripe_install`, `service_stripe_build`,
`service_atxp_install`, or `service_atxp_build` when a worker needs to isolate a
frozen pnpm install from `tsc -p tsconfig.json`. These manual tasks keep the
same frozen install flags and shared pnpm store as the default aggregate, but
they are not benchmark or gate profile members.
Offline service protocol tests are benchmark tasks too. Read
`service_offline_protocol_tests` for the aggregate result, then inspect
`service_offline_cdp`, `service_offline_stripe`, `service_offline_atxp`, and
`service_offline_ap2` for the exact credential-free helper tests that ran.
Those traces list `trace_metadata.validation.covered_test_files`,
`covered_helper_files`, `coverage_points`, and `semantic_surfaces` so coverage
gaps are visible without scraping command output. `semantic_surfaces` names the
newly gated helper contracts directly: CDP treasury transfer request/response
semantics, Stripe MPP session and settlement semantics, ATXP direct-transfer
and cdp-base top-up semantics, and AP2 nested mandate actor, merchant, and
amount semantics. The Node service tasks use the same frozen pnpm install and
node_modules seeding metadata as build tasks; AP2 runs its pure Python unittest
contract directly. The static benchmark contract also requires each service
coverage entry to list at least one test file, one helper file, and one semantic
surface, then checks that every listed path still exists. Deleting or renaming
one of those files, or moving one of those protocol contracts, requires updating
the metadata in the same change.
For the service-level contract map, start from `SERVICE_OFFLINE_COVERAGE` in
`benchmark_whole_app.py`, then follow the matching service docs:
`services/cdp/README.md`, `services/stripe/README.md`,
`services/atxp/README.md`, and `services/ap2/README.md`. Those READMEs name
the same semantic surfaces plus the helper and test files that enforce them;
`static_contracts` protects this architecture cross-reference and the README
references so workers should not need to hunt through source to find the map.

Focused service gates intentionally duplicate some of that validation after the
full benchmark. Treat duplicate focused gate validation as expected correctness
cost: `service_offline_protocol_tests` runs all offline service suites once,
then inherited gates may rerun `service_offline_ap2`,
`service_offline_stripe`, `service_offline_atxp`, or `service_offline_cdp`
against the same helper contracts. The duplicate cost is visible in
`trace_metadata.duplicate_validation` and task listing from
`benchmark_whole_app.py --list-tasks`; use it for budget planning, not as a
reason to remove, skip, merge, or weaken focused gates.

Manual Evo combines need a separate gate hygiene pass. Before applying a
winning diff outside its ancestry, run `evo gate list <source>` and
`evo gate list <destination>`, then reattach any focused gates that are present
on the source or parent but missing from the combined checkpoint.
`benchmark_whole_app.py --list-tasks` prints the benchmark-owned gate guidance
index, including command text and related task ids, so workers do not have to
hunt through source or old traces to find gate names. Keep
`whole_app_contract_gate` plus focused gates:
`ap2_offline_settlement_semantics` for `service_offline_ap2`,
`stripe_mpp_offline_semantics` for `service_offline_stripe`,
`atxp_offline_direct_transfer_topup_contract` for `service_offline_atxp`, and
`cdp_offline_treasury_transfer_contract` for `service_offline_cdp`. These gates
protect service protocol semantics even when a combine was created by patching
files rather than inheriting Evo metadata.

## Optimization Target

Future Evo work should optimize for believable ecosystem behavior:

- Protocol choices respond to fees, latency, reliability, capacity, workload,
  and social memory.
- Treasury rebalancing changes route pressure and rail P&L.
- Self-sustainability reports show rebalance outcomes, route pressure, and rail
  margin pressure as economy signals, not just funding diagnostics.
- The UI explains the simulation state through graph, timeline, report, and
  chat without treating funding status as the main product.
- Autonomous workers should continue from repo evidence: pick the next safe
  agent, merchant, route, treasury, report, or visualization improvement, run
  the relevant check, and only stop for a real blocker.
