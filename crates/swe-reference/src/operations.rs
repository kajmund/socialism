//! Application-layer operation contracts, needs and deterministic comparison.
//!
//! The workflow never decides *what to fetch*. That comes from operation
//! contracts: an operation declares the facts it must have (`required_inputs`),
//! and the plan handler derives the information-need list from those contracts —
//! before any supplier data has been read. A later screening round can discover
//! an additional conditional fact it cannot satisfy; it reports that as a
//! `NeedMore` result and the investigation resolves the new need before
//! re-running the operation.

use swe_native::Json;

use crate::domain::Candidate;
use crate::evidence::EvidenceSet;
use crate::{as_u64, field, field_array, field_str, obj, DemoError, DemoResult};

pub const COMPLIANCE_FACTS: [&str; 3] = ["req_a", "req_b", "req_c"];
pub const PRICE_FACT: &str = "price";
pub const EXCEPTION_FACT: &str = "c_exception";
pub const SCREEN_OPERATION: &str = "screen_compliance";
pub const PRICE_OPERATION: &str = "select_cheapest";

/// A fact a need refers to: `(supplier, fact)` with a stable id.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct NeedRef {
    pub id: String,
    pub supplier: String,
    pub fact: String,
}

impl NeedRef {
    pub fn new(supplier: impl Into<String>, fact: impl Into<String>) -> Self {
        let supplier = supplier.into();
        let fact = fact.into();
        Self {
            id: format!("{supplier}.{fact}"),
            supplier,
            fact,
        }
    }

    pub fn from_json(value: &Json) -> DemoResult<Self> {
        Ok(Self {
            id: field_str(value, "id")?.to_string(),
            supplier: field_str(value, "supplier")?.to_string(),
            fact: field_str(value, "fact")?.to_string(),
        })
    }

    pub fn to_json(&self) -> Json {
        obj([
            ("id", Json::from(self.id.as_str())),
            ("supplier", Json::from(self.supplier.as_str())),
            ("fact", Json::from(self.fact.as_str())),
        ])
    }
}

/// An information need derived from a contract (or discovered by an operation).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Need {
    pub reference: NeedRef,
    pub reason: String,
}

impl Need {
    pub fn new(reference: NeedRef, reason: impl Into<String>) -> Self {
        Self {
            reference,
            reason: reason.into(),
        }
    }

    pub fn to_json(&self) -> Json {
        obj([
            ("id", Json::from(self.reference.id.as_str())),
            ("supplier", Json::from(self.reference.supplier.as_str())),
            ("fact", Json::from(self.reference.fact.as_str())),
            ("reason", Json::from(self.reason.as_str())),
        ])
    }
}

/// One operation's declared inputs. This is what requirement planning reads.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OperationContract {
    pub id: String,
    pub required: Vec<NeedRef>,
}

impl OperationContract {
    pub fn new(id: impl Into<String>, required: Vec<NeedRef>) -> Self {
        Self {
            id: id.into(),
            required,
        }
    }

    pub fn to_json(&self) -> Json {
        obj([
            ("id", Json::from(self.id.as_str())),
            (
                "required",
                Json::Array(self.required.iter().map(NeedRef::to_json).collect()),
            ),
        ])
    }

    pub fn from_json(value: &Json) -> DemoResult<Self> {
        let required = field_array(value, "required")?
            .iter()
            .map(NeedRef::from_json)
            .collect::<DemoResult<Vec<_>>>()?;
        Ok(Self {
            id: field_str(value, "id")?.to_string(),
            required,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OperationRegistry {
    pub contracts: Vec<OperationContract>,
}

impl OperationRegistry {
    /// Derive the contracts for a candidate set. Nothing here depends on
    /// resolved supplier data; the registry is an application constant shaped by
    /// the candidate list.
    pub fn for_candidates(candidates: &[Candidate]) -> Self {
        let compliance = candidates
            .iter()
            .flat_map(|candidate| {
                COMPLIANCE_FACTS
                    .iter()
                    .map(move |fact| NeedRef::new(&candidate.id, *fact))
            })
            .collect();
        let prices = candidates
            .iter()
            .map(|candidate| NeedRef::new(&candidate.id, PRICE_FACT))
            .collect();
        Self {
            contracts: vec![
                OperationContract::new(SCREEN_OPERATION, compliance),
                OperationContract::new(PRICE_OPERATION, prices),
            ],
        }
    }

    pub fn to_json(&self) -> Json {
        Json::Array(
            self.contracts
                .iter()
                .map(OperationContract::to_json)
                .collect(),
        )
    }

    pub fn from_json(value: &Json) -> DemoResult<Self> {
        let items = value
            .as_array()
            .ok_or_else(|| DemoError::new("operations must be an array"))?;
        Ok(Self {
            contracts: items
                .iter()
                .map(OperationContract::from_json)
                .collect::<DemoResult<Vec<_>>>()?,
        })
    }

    pub fn contract(&self, operation: &str) -> DemoResult<&OperationContract> {
        self.contracts
            .iter()
            .find(|contract| contract.id == operation)
            .ok_or_else(|| DemoError::new(format!("operation {operation:?} was not planned")))
    }

    fn needs(&self, operation: &str) -> DemoResult<Vec<Need>> {
        let contract = self.contract(operation)?;
        Ok(contract
            .required
            .iter()
            .map(|reference| {
                Need::new(
                    reference.clone(),
                    format!("operation {operation} declares this fact as a required input"),
                )
            })
            .collect())
    }
}

/// A required input the ALL_REQUIRED gate could not accept.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MissingInput {
    pub need: NeedRef,
    pub reason: String,
}

impl MissingInput {
    pub fn to_json(&self) -> Json {
        obj([
            ("need", self.need.to_json()),
            ("reason", Json::from(self.reason.as_str())),
        ])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GateResult {
    pub missing: Vec<MissingInput>,
}

impl GateResult {
    pub fn satisfied(&self) -> bool {
        self.missing.is_empty()
    }

    pub fn to_json(&self) -> Json {
        Json::Array(self.missing.iter().map(MissingInput::to_json).collect())
    }

    pub fn summary(&self) -> String {
        self.missing
            .iter()
            .map(|input| input.need.id.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    }
}

/// ALL_REQUIRED: every declared input must have VERIFIED evidence.
///
/// There is no partial pass and no fallback: `AMBIGUOUS` and `REJECTED` both
/// count as missing, and the gate returns the exact list.
pub fn all_required(required: &[NeedRef], evidence: &EvidenceSet) -> GateResult {
    let mut missing = Vec::new();
    for need in required {
        match evidence.get(&need.id) {
            None => missing.push(MissingInput {
                need: need.clone(),
                reason: "no evidence recorded for this required input".to_string(),
            }),
            Some(entry) if !entry.is_verified() => missing.push(MissingInput {
                need: need.clone(),
                reason: format!("{}: {}", entry.status.as_str(), entry.reason),
            }),
            Some(_) => {}
        }
    }
    GateResult { missing }
}

/// Handler that plans the information needs from operation contracts.
pub fn plan_needs_handler(input: &Json) -> DemoResult<Json> {
    let candidates = Candidate::list_from_json(field(input, "candidates")?)?;
    let registry = OperationRegistry::for_candidates(&candidates);
    let compliance = registry.needs(SCREEN_OPERATION)?;
    let prices = registry.needs(PRICE_OPERATION)?;
    let total = compliance.len() + prices.len();
    Ok(obj([
        (
            "needs_compliance",
            Json::Array(compliance.iter().map(Need::to_json).collect()),
        ),
        (
            "needs_prices",
            Json::Array(prices.iter().map(Need::to_json).collect()),
        ),
        ("operations", registry.to_json()),
        ("required_inputs_total", Json::from_usize(total)),
    ]))
}

/// Typed operation result, before it is serialised into the handler's JSON.
///
/// `NeedMore` is the spec's `NeedMore(NeedRef)` protocol: the operation found a
/// fact that its declared contract does not cover and that it therefore cannot
/// satisfy itself. The handler layer serialises this outcome to the flat task
/// output (`status: "need_more"`), routes the new needs through the same
/// fan-out, and re-runs the operation.
#[derive(Clone, Debug, PartialEq)]
pub enum OpOutcome {
    Answer(Json),
    NeedMore(Vec<Need>),
    Insufficient(Json),
}

impl OpOutcome {
    pub fn status(&self) -> &'static str {
        match self {
            Self::Answer(_) => "ok",
            Self::NeedMore(_) => "need_more",
            Self::Insufficient(_) => "insufficient",
        }
    }

    /// Serialise into the flat JSON object a `task` handler returns.
    pub fn into_json(self) -> Json {
        match self {
            Self::Answer(payload) => with_status(payload, "ok"),
            Self::NeedMore(needs) => obj([
                ("status", Json::from("need_more")),
                (
                    "needs",
                    Json::Array(needs.iter().map(Need::to_json).collect()),
                ),
                (
                    "reason",
                    Json::from(
                        "the operation discovered additional conditional facts it cannot satisfy",
                    ),
                ),
            ]),
            Self::Insufficient(payload) => with_status(payload, "insufficient"),
        }
    }
}

fn with_status(payload: Json, status: &str) -> Json {
    match payload {
        Json::Object(mut map) => {
            map.insert("status".to_string(), Json::from(status));
            Json::Object(map)
        }
        other => other,
    }
}

enum Screening {
    Compliant(String),
    NonCompliant(String),
    NeedsException(Need),
    Insufficient(String),
}

/// Handler wrapper: serialises the typed [`OpOutcome`] for the kernel.
pub fn screen_compliance_handler(input: &Json) -> DemoResult<Json> {
    Ok(screen_compliance(input)?.into_json())
}

/// Screening operation: ALL_REQUIRED gate, then the requirements rule.
///
/// Requirement C has a documented-exception path. When a candidate fails C the
/// operation discovers that it needs the exception fact, which is *not* part of
/// its static contract; it returns [`OpOutcome::NeedMore`] for it.
pub fn screen_compliance(input: &Json) -> DemoResult<OpOutcome> {
    let candidates = Candidate::list_from_json(field(input, "candidates")?)?;
    let registry = OperationRegistry::from_json(field(input, "operations")?)?;
    let evidence = EvidenceSet::from_json(field(input, "evidence")?)?;
    let contract = registry.contract(SCREEN_OPERATION)?;
    let gate = all_required(&contract.required, &evidence);
    if !gate.satisfied() {
        return Ok(OpOutcome::Insufficient(insufficient_payload(
            SCREEN_OPERATION,
            &gate,
        )));
    }

    let mut needs = Vec::new();
    let mut compliant = Vec::new();
    let mut supplier_states = Vec::new();
    for candidate in &candidates {
        match screen_candidate(candidate, &evidence)? {
            Screening::Compliant(reason) => {
                compliant.push(candidate.id.clone());
                supplier_states.push(supplier_state(candidate, true, reason));
            }
            Screening::NonCompliant(reason) => {
                supplier_states.push(supplier_state(candidate, false, reason));
            }
            Screening::NeedsException(need) => needs.push(need),
            Screening::Insufficient(reason) => {
                return Ok(OpOutcome::Insufficient(obj([(
                    "reason",
                    Json::from(reason),
                )])));
            }
        }
    }

    if !needs.is_empty() {
        return Ok(OpOutcome::NeedMore(needs));
    }

    Ok(OpOutcome::Answer(obj([
        (
            "compliant",
            Json::Array(compliant.iter().map(|id| Json::from(id.as_str())).collect()),
        ),
        ("supplier_states", Json::Array(supplier_states)),
        ("gate", obj([("satisfied", Json::Bool(true))])),
    ])))
}

fn screen_candidate(candidate: &Candidate, evidence: &EvidenceSet) -> DemoResult<Screening> {
    let req_a = required_bool(evidence, &candidate.id, "req_a")?;
    let req_b = required_bool(evidence, &candidate.id, "req_b")?;
    let req_c = required_bool(evidence, &candidate.id, "req_c")?;
    if !req_a {
        return Ok(Screening::NonCompliant(
            "requirement A is not met".to_string(),
        ));
    }
    if !req_b {
        return Ok(Screening::NonCompliant(
            "requirement B is not met".to_string(),
        ));
    }
    if req_c {
        return Ok(Screening::Compliant(
            "meets requirements A, B and C".to_string(),
        ));
    }
    let exception = NeedRef::new(&candidate.id, EXCEPTION_FACT);
    match evidence.get(&exception.id) {
        None => Ok(Screening::NeedsException(Need::new(
            exception,
            format!(
                "requirement C is not met for {}; the screening rule needs the documented exception before it can decide",
                candidate.name
            ),
        ))),
        Some(entry) if !entry.is_verified() => Ok(Screening::Insufficient(format!(
            "INSUFFICIENT_EVIDENCE: exception fact {} is {}: {}",
            exception.id,
            entry.status.as_str(),
            entry.reason
        ))),
        Some(entry) => {
            if entry.value.as_bool() == Some(true) {
                Ok(Screening::Compliant(
                    "meets requirements A and B; requirement C is covered by a granted exception"
                        .to_string(),
                ))
            } else {
                Ok(Screening::NonCompliant(
                    "requirement C is not met and no exception is granted".to_string(),
                ))
            }
        }
    }
}

fn required_bool(evidence: &EvidenceSet, supplier: &str, fact: &str) -> DemoResult<bool> {
    let need = NeedRef::new(supplier, fact);
    evidence.verified_bool(&need.id).ok_or_else(|| {
        DemoError::new(format!(
            "ALL_REQUIRED gate passed but {} is not a verified boolean",
            need.id
        ))
    })
}

fn supplier_state(candidate: &Candidate, compliant: bool, reason: String) -> Json {
    obj([
        ("supplier", Json::from(candidate.id.as_str())),
        ("name", Json::from(candidate.name.as_str())),
        ("compliant", Json::Bool(compliant)),
        ("reason", Json::from(reason.as_str())),
    ])
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RankedSupplier {
    pub id: String,
    pub name: String,
    pub price_sek: u64,
}

impl RankedSupplier {
    pub fn to_json(&self) -> Json {
        obj([
            ("id", Json::from(self.id.as_str())),
            ("name", Json::from(self.name.as_str())),
            ("price_sek", Json::from_u64(self.price_sek)),
        ])
    }
}

/// Deterministic comparison: lowest price among compliant suppliers, tie-broken
/// by supplier id so the result never depends on map ordering.
pub fn cheapest_compliant(
    candidates: &[Candidate],
    compliant: &[String],
    evidence: &EvidenceSet,
) -> DemoResult<Vec<RankedSupplier>> {
    let mut ranked = Vec::new();
    for candidate in candidates {
        if !compliant.iter().any(|id| id == &candidate.id) {
            continue;
        }
        let need = NeedRef::new(&candidate.id, PRICE_FACT);
        let price_sek = evidence.verified_u64(&need.id).ok_or_else(|| {
            DemoError::new(format!(
                "compliant supplier {} has no verified price evidence",
                candidate.id
            ))
        })?;
        ranked.push(RankedSupplier {
            id: candidate.id.clone(),
            name: candidate.name.clone(),
            price_sek,
        });
    }
    ranked.sort_by(|left, right| {
        left.price_sek
            .cmp(&right.price_sek)
            .then_with(|| left.id.cmp(&right.id))
    });
    Ok(ranked)
}

/// Handler wrapper: serialises the typed [`OpOutcome`] for the kernel.
pub fn select_cheapest_handler(input: &Json) -> DemoResult<Json> {
    Ok(select_cheapest(input)?.into_json())
}

/// Price operation: ALL_REQUIRED gate, then the deterministic comparison.
pub fn select_cheapest(input: &Json) -> DemoResult<OpOutcome> {
    let candidates = Candidate::list_from_json(field(input, "candidates")?)?;
    let registry = OperationRegistry::from_json(field(input, "operations")?)?;
    let evidence = EvidenceSet::from_json(field(input, "evidence")?)?;
    let compliant = field_array(input, "compliant")?
        .iter()
        .map(|item| {
            item.as_str()
                .map(ToString::to_string)
                .ok_or_else(|| DemoError::new("compliant supplier ids must be strings"))
        })
        .collect::<DemoResult<Vec<_>>>()?;
    let contract = registry.contract(PRICE_OPERATION)?;
    let gate = all_required(&contract.required, &evidence);
    if !gate.satisfied() {
        return Ok(OpOutcome::Insufficient(insufficient_payload(
            PRICE_OPERATION,
            &gate,
        )));
    }
    let ranked = cheapest_compliant(&candidates, &compliant, &evidence)?;
    let Some(winner) = ranked.first() else {
        return Ok(OpOutcome::Answer(obj([
            ("answer", Json::Null),
            ("ranked", Json::Array(Vec::new())),
            (
                "reason",
                Json::from("no supplier meets all three requirements"),
            ),
        ])));
    };
    Ok(OpOutcome::Answer(obj([
        ("answer", winner.to_json()),
        (
            "ranked",
            Json::Array(ranked.iter().map(RankedSupplier::to_json).collect()),
        ),
        (
            "reason",
            Json::from(format!(
                "{} has the lowest price ({} SEK) among {} compliant supplier(s)",
                winner.name,
                winner.price_sek,
                ranked.len()
            )),
        ),
    ])))
}

/// Final report on the completed investigation.
pub fn build_report_handler(input: &Json) -> DemoResult<Json> {
    let screen = field(input, "screen")?;
    let price = field(input, "price")?;
    let evidence = EvidenceSet::from_json(field(input, "evidence")?)?;
    let answer = field(price, "answer")?;
    let conclusion = field_str(answer, "name")?;
    let conclusion_id = field_str(answer, "id")?;
    let price_sek = as_u64(field(answer, "price_sek")?)
        .ok_or_else(|| DemoError::new("answer.price_sek must be an unsigned integer"))?;
    let reason = field_str(price, "reason")?;
    Ok(obj([
        ("status", Json::from("ok")),
        ("conclusion", Json::from(conclusion)),
        ("conclusion_id", Json::from(conclusion_id)),
        ("price_sek", Json::from_u64(price_sek)),
        ("reason", Json::from(reason)),
        (
            "supplier_states",
            screen
                .get("supplier_states")
                .cloned()
                .unwrap_or(Json::Array(Vec::new())),
        ),
        ("evidence", evidence.to_json()),
        ("evidence_status_counts", evidence.counts().to_json()),
    ]))
}

/// Terminal abstention: incomplete run with an explicit reason.
pub fn build_abstain_handler(input: &Json) -> DemoResult<Json> {
    let reason = field_str(input, "reason")?;
    let evidence = EvidenceSet::from_json(field(input, "evidence")?)?;
    Ok(obj([
        ("status", Json::from("INSUFFICIENT_EVIDENCE")),
        ("conclusion", Json::from("INSUFFICIENT_EVIDENCE")),
        ("reason", Json::from(reason)),
        ("evidence", evidence.to_json()),
        ("evidence_status_counts", evidence.counts().to_json()),
    ]))
}

fn insufficient_payload(operation: &str, gate: &GateResult) -> Json {
    obj([
        (
            "reason",
            Json::from(format!(
                "INSUFFICIENT_EVIDENCE: operation {operation} ALL_REQUIRED gate is missing {} required input(s): {}",
                gate.missing.len(),
                gate.summary()
            )),
        ),
        ("missing", gate.to_json()),
    ])
}
