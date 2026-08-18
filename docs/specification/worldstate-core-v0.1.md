# WorldState Core Specification v0.1

**Status:** Draft / M0 Contract Freeze Candidate  
**Scope:** Public Core semantics, contracts, invariants, and reference-engine boundary  
**Strategic basis:** AgentReality Stack Strategic Architecture Specification v2.1  
**Question owned by this project:** **What is true about the world?**

---

## 0. Executive decision

WorldState SHALL be an **open, lightweight, domain-neutral world-state foundation**.

The Core SHALL represent evidence-grounded state while preserving:

- provenance;
- temporal validity;
- epistemic mode;
- uncertainty;
- unknowns;
- conflicts;
- history and replayability.

The Core SHALL NOT require:

- a specific database;
- a graph database;
- GIS infrastructure;
- an Agent Harness;
- GeoTask;
- AgentReality;
- Lowa;
- GSTAR;
- a web server;
- distributed infrastructure.

The initial implementation strategy is:

```text
Contracts
  ↓
Invariants
  ↓
Deterministic in-memory reference engine
  ↓
Conformance tests
  ↓
Projection / external-provider proof
  ↓
Cross-domain proof
```

---

# 1. Semantic boundary

## 1.1 WorldState owns

```text
Entity identity/reference
Observation
Source
Evidence
Claim
StateAssertion
Relation assertion
SpatialScope
TemporalScope
Validity
Provenance
Uncertainty
Unknown
Conflict
Snapshot
StateTransition
Version
World-state resolution semantics
Provider conformance semantics
```

## 1.2 WorldState does not own

```text
Task relevance
Task applicability
Task resolution adequacy
Task sufficiency
Task context construction
Agent session / run lifecycle
Agent loop
Tool execution
Domain assessment
Recommendation
Authorization
Execution
Business workflow
```

Hard invariant:

> **WorldState does not know the Task.**

---

# 2. Semantic pipeline

The normative conceptual pipeline is:

```text
Source
  ↓
Observation / authoritative record
  ↓
Evidence
  ↓
Claim
  ↓
Resolution
  ├── StateAssertion
  ├── Unknown
  └── Conflict
  ↓
WorldStateSnapshot
  ↓
StateTransition / History
```

Important distinction:

> Evidence is not state. A Claim is not resolved truth. A StateAssertion is not necessarily timeless truth.

Every state result is scoped by provenance, validity, and epistemic mode.

---

# 3. Core value model

WorldState Core SHALL treat domain values as opaque serializable values.

M0 MUST NOT define domain-specific value classes such as airport, site, facility, weather rule, telecom cell, or business status.

A property is identified by a stable string key:

```text
entity_ref + property_key
```

Examples used in tests SHOULD remain generic:

```text
thing-1 / status
thing-2 / temperature
thing-3 / location
```

Domain packages MAY define richer schemas outside Core.

---

# 4. Core contracts

## 4.1 EntityRef

An `EntityRef` identifies a real, inferred, predicted, or simulated entity without requiring WorldState Core to own that entity's master record.

Minimum fields:

```text
entity_id: str
entity_type: str | None
namespace: str | None
```

Rules:

1. `entity_id` MUST be non-empty.
2. `namespace` SHOULD be used when identifiers are not globally unique.
3. WorldState MUST NOT silently merge two entity references only because labels are similar.
4. Entity resolution is an explicit adapter/domain concern unless a later Core specification defines a generic contract.

---

## 4.2 Source

A `Source` describes where evidence originated.

Minimum fields:

```text
source_id: str
source_type: str
uri: str | None
version: str | None
metadata: Mapping[str, JSONValue]
```

`source_type` is descriptive, not an authority ranking.

Core MUST NOT assume that a government source, sensor, model, user, database, or web source is universally more authoritative than another. Authority policy is context/provider specific.

---

## 4.3 TemporalScope

`TemporalScope` expresses the interval in world time for which a fact, observation, or assertion applies.

```text
start: datetime | None
end: datetime | None
```

Rules:

- bounds are UTC-aware datetimes when present;
- `None` denotes an open bound, not unknown time;
- an unknown time MUST be represented explicitly in metadata or uncertainty, not silently converted to an unbounded interval;
- `end < start` is invalid.

---

## 4.4 SpatialScope

`SpatialScope` is a domain-neutral scope reference.

M0 SHALL NOT embed a mandatory GIS geometry library.

Minimum fields:

```text
kind: str
reference: str | None
bbox: tuple[float, float, float, float] | None
metadata: Mapping[str, JSONValue]
```

This allows a provider to use:

- a named place reference;
- a grid/cell reference;
- a bounding box;
- an external geometry URI or ID.

Rich geometry adapters belong outside the dependency-free Core.

---

## 4.5 EpistemicMode

Every claim/assertion that describes state MUST identify how that state is known.

Normative enum:

```text
OBSERVED
INFERRED
PREDICTED
SIMULATED
```

Rules:

- modes MUST NOT be silently converted;
- a prediction becoming observed requires a new observation/assertion, not mutation of the old record;
- simulated state MUST never be returned as observed state.

---

## 4.6 Observation

An `Observation` is a record that something was observed or supplied at a particular world/system time.

Minimum fields:

```text
observation_id: str
entity: EntityRef
property_key: str
value: JSONValue
source: Source
observed_at: datetime | None
recorded_at: datetime
spatial_scope: SpatialScope | None
temporal_scope: TemporalScope | None
metadata: Mapping[str, JSONValue]
```

`observed_at` and `recorded_at` are deliberately separate:

- `observed_at`: when the described observation occurred in the world;
- `recorded_at`: when WorldState/provider recorded the observation.

This separation is required for replay and delayed-ingestion reasoning.

---

## 4.7 Evidence

`Evidence` wraps one or more source-backed records supporting or contradicting a proposition.

Minimum fields:

```text
evidence_id: str
source: Source
observation_refs: tuple[str, ...]
content_ref: str | None
content_hash: str | None
recorded_at: datetime
metadata: Mapping[str, JSONValue]
```

Rules:

1. Evidence MUST remain traceable to a source.
2. Evidence IDs MUST be stable within a provider/replay boundary.
3. Core SHOULD store references/hashes rather than forcing large raw payloads into snapshots.
4. Evidence deletion or source unavailability MUST NOT silently erase the fact that an assertion depended on it.

---

## 4.8 Provenance

`Provenance` records how a claim/assertion came to exist.

Minimum fields:

```text
evidence_refs: tuple[str, ...]
source_refs: tuple[str, ...]
parent_assertion_refs: tuple[str, ...]
method: str
resolver: str | None
```

Examples of `method`:

```text
direct-observation
projection
rule-inference
model-inference
simulation
manual-assertion
```

Core MUST NOT interpret these strings as universal quality scores.

---

## 4.9 Uncertainty

`Uncertainty` communicates uncertainty without forcing heterogeneous evidence into a single universal probability model.

Minimum fields:

```text
confidence: float | None
method: str | None
reason: str | None
metadata: Mapping[str, JSONValue]
```

Rules:

- when present, `confidence` MUST be in `[0, 1]`;
- confidence values from different methods MUST NOT be compared automatically unless a resolution policy explicitly declares them comparable;
- absence of confidence is not confidence zero.

---

## 4.10 Claim

A `Claim` is an evidence-backed proposition proposed for resolution.

Minimum fields:

```text
claim_id: str
entity: EntityRef
property_key: str
value: JSONValue
epistemic_mode: EpistemicMode
temporal_scope: TemporalScope | None
spatial_scope: SpatialScope | None
provenance: Provenance
uncertainty: Uncertainty | None
created_at: datetime
```

A Claim MUST NOT be exposed as resolved truth solely because it exists.

---

## 4.11 Validity

`Validity` describes the applicability and status of a resolved assertion.

Minimum fields:

```text
valid_from: datetime | None
valid_until: datetime | None
resolved_at: datetime
superseded_by: str | None
```

M0 treats validity as temporal validity only. Task applicability belongs to GeoTask and MUST NOT be added here.

---

## 4.12 StateAssertion

A `StateAssertion` is a resolved world-state proposition.

Minimum fields:

```text
assertion_id: str
entity: EntityRef
property_key: str
value: JSONValue
epistemic_mode: EpistemicMode
validity: Validity
provenance: Provenance
uncertainty: Uncertainty | None
spatial_scope: SpatialScope | None
version: str
```

Invariant:

> A `StateAssertion` MUST have non-empty provenance.

A resolver that cannot provide provenance MUST return `Unknown` or a resolution error, not an unsupported assertion.

---

## 4.13 Relation

A relation is represented as an assertion whose value references another entity.

Conceptually:

```text
subject --relation_key--> object
```

M0 SHOULD expose a `RelationAssertion` convenience type, but MUST NOT require graph persistence.

---

## 4.14 Unknown

`Unknown` is a successful, first-class query/resolution result stating that WorldState cannot currently support a requested state proposition.

Minimum fields:

```text
unknown_id: str
entity: EntityRef | None
property_key: str | None
reason: UnknownReason
missing: tuple[str, ...]
as_of: datetime
metadata: Mapping[str, JSONValue]
```

Initial `UnknownReason` values:

```text
NO_EVIDENCE
INSUFFICIENT_EVIDENCE
OUTSIDE_VALIDITY
PROVIDER_UNAVAILABLE
UNRESOLVED_IDENTITY
UNSUPPORTED_QUERY
```

Hard rule:

> `Unknown` MUST NOT be replaced by guessed/default state to increase coverage.

---

## 4.15 Conflict

`Conflict` is a first-class result representing materially incompatible supported claims/assertions that the active resolution policy cannot safely reconcile.

Minimum fields:

```text
conflict_id: str
entity: EntityRef
property_key: str
candidate_refs: tuple[str, ...]
evidence_refs: tuple[str, ...]
reason: str
as_of: datetime
metadata: Mapping[str, JSONValue]
```

Rules:

1. Conflict is not an exception by default.
2. Conflict is not equivalent to Unknown.
3. A policy MAY resolve a conflict only if its resolution rule is explicit and provenance-preserving.
4. The losing candidate/evidence history MUST remain inspectable.

---

## 4.16 StateQueryResult

Although the strategic interface sketches `query_state(...) -> StateAssertion`, the M0 contract strengthens this to preserve first-class uncertainty:

```text
StateQueryResult = StateAssertion | Unknown | Conflict
```

This is a deliberate semantic refinement, not a change of ownership.

A caller MUST be able to distinguish all three outcomes without parsing exceptions or metadata strings.

---

## 4.17 WorldStateSnapshot

A `WorldStateSnapshot` is an immutable, replayable view of world state for a scope and `as_of` boundary.

Minimum fields:

```text
snapshot_id: str
as_of: datetime
scope: SpatialScope | None
assertions: tuple[StateAssertion, ...]
unknowns: tuple[Unknown, ...]
conflicts: tuple[Conflict, ...]
source_versions: Mapping[str, str]
created_at: datetime
version: str
```

Rules:

- snapshots MUST be immutable values;
- creating a new snapshot MUST NOT mutate a previous snapshot;
- ordering MUST be canonical/deterministic;
- snapshot identity SHOULD be content-derived or otherwise replay-stable;
- a snapshot MUST preserve explicit unknown/conflict outcomes when they are part of the requested scope.

---

## 4.18 StateTransition

A `StateTransition` links two assertion states over time without deleting history.

Minimum fields:

```text
transition_id: str
entity: EntityRef
property_key: str
from_assertion_ref: str | None
to_assertion_ref: str | None
transition_time: datetime
reason: str | None
provenance: Provenance
```

A transition may represent creation, supersession, invalidation, or change.

---

# 5. Resolution semantics

## 5.1 Resolution is explicit

WorldState SHALL distinguish:

```text
collecting records
creating claims
resolving state
querying state
```

These operations MUST NOT be collapsed into a setter such as:

```text
set_truth(key, value)
```

without provenance and validity semantics.

## 5.2 M1 reference resolution baseline

The first deterministic resolver SHOULD intentionally be conservative:

1. Select claims matching entity/property and time scope.
2. Reject claims with missing required provenance.
3. If no usable claim remains → `Unknown`.
4. If usable claims agree on value and epistemic mode → emit one `StateAssertion` referencing all supporting evidence.
5. If materially incompatible claims remain → `Conflict`.
6. Do not auto-select by confidence, newest timestamp, or source type unless an explicit policy is supplied.

This weak baseline is intentional. It provides a trustworthy conformance target before sophisticated policy is added.

## 5.3 ResolutionPolicy seam

Later engines MAY accept an explicit `ResolutionPolicy` protocol.

A policy MUST declare:

- which candidate classes it can compare;
- authority/precedence rules if any;
- confidence-comparability assumptions;
- tie/conflict behavior;
- whether unresolved cases become `Conflict` or `Unknown`;
- a stable policy identifier/version.

Policy behavior MUST be replayable.

---

# 6. Provider contracts

## 6.1 WorldStateProvider

The provider contract represents semantic interoperability, not a required implementation architecture.

M0/M1 synchronous read protocol:

```python
class WorldStateProvider(Protocol):
    def get_snapshot(self, scope, at) -> WorldStateSnapshot: ...
    def query_state(self, entity, property_key, at) -> StateQueryResult: ...
    def query_relation(self, subject, relation_key, object, at) -> StateQueryResult: ...
    def get_evidence(self, state_ref) -> EvidenceSet: ...
    def get_unknowns(self, scope) -> tuple[Unknown, ...]: ...
    def get_conflicts(self, scope) -> tuple[Conflict, ...]: ...
    def get_history(self, entity, interval) -> tuple[StateTransition, ...]: ...
```

## 6.2 Change stream seam

`subscribe_changes` is strategically important but NOT part of the mandatory M0 synchronous provider protocol.

A separate optional protocol SHOULD later define:

```text
WorldStateChangeProvider
```

This avoids forcing async/event infrastructure into every conforming provider.

---

# 7. Deployment modes

## Mode A — Native

WorldState engine owns its own state persistence.

```text
Observation → Evidence → Claim → Resolve → Store → Snapshot
```

Native persistence is optional and not an M0 requirement.

## Mode B — Projection

An existing System of Record remains authoritative.

```text
Existing SoR
   ↓ read-only adapter
WorldState contracts
   ↓
Snapshot / query
```

This mode MUST be first-class and MUST NOT be treated as a temporary hack.

## Mode C — External Provider

An independent world model implements `WorldStateProvider` directly.

```text
External model / GIS / Digital Twin
   ↓
WorldStateProvider
```

Core MUST NOT require external providers to re-persist their data in WorldState.

---

# 8. Identity and replay

## 8.1 Stable IDs

Reference implementation IDs SHOULD be deterministic where the semantic payload is immutable.

Recommended approach:

```text
canonical semantic payload
  ↓
stable serialization
  ↓
SHA-256 digest
  ↓
typed ID prefix
```

Examples:

```text
obs_<digest>
ev_<digest>
claim_<digest>
state_<digest>
snap_<digest>
conflict_<digest>
unknown_<digest>
```

M0 tests SHALL verify that mapping/dictionary key order does not alter semantic IDs.

## 8.2 Replayability

Given:

- identical normalized inputs;
- identical policy version;
- identical `as_of` boundary;

The reference resolver MUST produce semantically identical results and stable IDs.

Wall-clock timestamps MUST NOT leak into deterministic state identity unless they are explicit semantic inputs.

---

# 9. Immutability and history

Core contract values SHOULD be immutable dataclasses/value objects.

State evolution SHALL create new assertions/snapshots/transitions rather than mutating prior records.

This enables:

- audit;
- replay;
- diff;
- historical query;
- deterministic testing.

---

# 10. Failure semantics

Core distinguishes:

```text
Unknown       = no defensible supported answer
Conflict      = multiple incompatible supported answers
InvalidInput  = caller violated contract
ProviderError = provider could not execute the query
```

A provider outage SHOULD become `Unknown(PROVIDER_UNAVAILABLE)` when the provider can safely express that semantic result. Infrastructure exceptions may still surface when no valid response can be constructed.

Never map infrastructure failure to a positive state assertion.

---

# 11. Public API layering

Target package layout:

```text
worldstate
├── models.py        immutable semantic values
├── ids.py           canonicalization and stable IDs
├── provider.py      provider protocols
├── resolution.py    resolver/policy protocols + reference resolver
├── snapshot.py      snapshot construction
├── history.py       transition helpers
└── errors.py        contract/infrastructure errors
```

Optional integrations MUST live outside the dependency-free semantic core, for example:

```text
worldstate.adapters.*
worldstate.integrations.*
```

Domain-specific adapters SHOULD preferably live in their owning projects.

---

# 12. Testing strategy

## 12.1 Invariant tests

Required from M0:

- invalid temporal interval rejected;
- non-UTC/naive datetime rejected or normalized only by explicit helper;
- confidence outside `[0,1]` rejected;
- assertion without provenance rejected;
- observed/inferred/predicted/simulated modes preserved;
- Unknown is not StateAssertion;
- Conflict is not Unknown;
- immutable snapshots cannot be mutated.

## 12.2 Determinism tests

- stable IDs across mapping order;
- repeated resolution produces same semantic result;
- snapshot ordering deterministic;
- replay with same policy/version stable.

## 12.3 Resolution tests

- no evidence → Unknown;
- one supported claim → assertion;
- multiple agreeing claims → assertion with combined provenance;
- incompatible claims → Conflict;
- expired claims → Unknown(OUTSIDE_VALIDITY);
- missing provenance → fail closed.

## 12.4 Provider conformance tests

A reusable conformance suite SHALL validate third-party providers against the public semantic contract.

---

# 13. Metrics

North Star:

> **Truth Fidelity**

Initial measurement framework:

| Metric | Meaning |
|---|---|
| State Correctness | Supported resolved state matches benchmark/authoritative reference |
| Freshness | State remains within declared temporal validity/freshness requirements |
| Provenance Coverage | Resolved assertions with inspectable provenance |
| Unknown Fidelity | Unknown remains Unknown when evidence is insufficient |
| Conflict Preservation | Material conflicts are surfaced rather than hidden |
| Validity Accuracy | State is returned only within supported validity scope |
| Replayability | Same bounded inputs/policy reproduce the same semantic state |
| Unsupported State Rate | Positive assertions lacking sufficient support |

The counter-metric `Unsupported State Rate` MUST be reported beside positive coverage/correctness metrics when applicable.

---

# 14. Independence gates

Before calling the Core foundation-ready:

## Gate A — No Task dependency

Core imports and public contracts contain no GeoTask task-context semantics.

## Gate B — No Harness dependency

Core runs as a normal library without an Agent Harness.

## Gate C — No domain dependency

At least two unrelated example domains use the same Core without modifying it.

## Gate D — No persistence dependency

In-memory tests and external-provider conformance work without a database.

## Gate E — Projection parity

A read-only projection provider can expose state from an external System of Record without migrating its authoritative data.

---

# 15. Explicit non-goals for v0.1

The following are deferred:

- distributed storage;
- graph query language;
- vector search;
- geospatial topology engine;
- ontology framework;
- entity-resolution platform;
- generic event bus;
- streaming runtime;
- scheduler/workflow;
- agent tools/MCP packaging;
- GeoTask context construction;
- AgentReality grounding hooks;
- Lowa production migration;
- GSTAR internals;
- UI/admin console;
- hosted service.

Deferral is intentional architecture, not missing ambition.

---

# 16. M0 acceptance criteria

M0 is complete only when:

1. Core semantic contracts exist as typed immutable Python values.
2. `StateQueryResult` represents assertion/unknown/conflict explicitly.
3. Stable semantic-ID helpers exist.
4. `WorldStateProvider` synchronous protocol exists.
5. All invariant tests pass.
6. Core runtime dependencies are zero or justified by an accepted ADR.
7. No domain/task/harness vocabulary leaks into Core contracts.
8. README and specification agree with the public API.
9. Initial CI runs tests on supported Python versions.
10. A license decision is made explicitly rather than accidentally inferred from another project.

---

# 17. M1 acceptance criteria

M1 adds the smallest useful reference engine:

1. ingest observations/evidence/claims in memory;
2. deterministic conservative resolution;
3. explicit Unknown/Conflict preservation;
4. immutable snapshot construction;
5. evidence lookup;
6. transition/history generation;
7. replay determinism tests;
8. provider conformance suite consumes the reference engine.

M1 MUST NOT add production database infrastructure.

---

# 18. Strategic summary

WorldState v0.1 is successful if a developer can say:

> I can represent what my system currently knows about the world, show why it believes that state, show when the state is valid, preserve what it does not know or cannot reconcile, replay the result, and expose the same semantics whether the data is native, projected, or external.

It is unsuccessful if the project becomes:

> a task engine, Agent platform, domain product, or mandatory data platform under a world-model name.

The governing principle is:

> **Own the semantics of world state; do not demand ownership of every system that stores or uses it.**
