//! Pack one fleet run trace (JSONL) into content-addressed evidence blocks with a Merkle root.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashSet};
use std::fmt;
use std::io::{BufRead, Write};

pub const PARAM_KEYS: [&str; 8] = [
    "model",
    "temperature",
    "top_p",
    "max_tokens",
    "seed",
    "reasoning",
    "response_format",
    "stop",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DataClass {
    Synthetic,
    Preclinical,
    Clinical,
    HumanSequence,
}

impl DataClass {
    fn parse(s: &str) -> Option<Self> {
        match s {
            "synthetic" => Some(Self::Synthetic),
            "preclinical" => Some(Self::Preclinical),
            "clinical" => Some(Self::Clinical),
            "human_sequence" => Some(Self::HumanSequence),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    DidNotRun(String),
    Pack(String),
    Verify(String),
    ExportRefused(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DidNotRun(m) => write!(f, "DID NOT RUN: {m}"),
            Self::Pack(m) => write!(f, "pack: {m}"),
            Self::Verify(m) => write!(f, "verify: {m}"),
            Self::ExportRefused(m) => write!(f, "export refused: {m}"),
        }
    }
}

impl std::error::Error for Error {}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Block {
    pub data_class: String,
    pub consent_ref: Option<String>,
    pub body: Value,
}

#[derive(Debug, Clone)]
pub struct PackedRun {
    pub root: String,
    pub leaves: Vec<String>,
    pub blocks: BTreeMap<String, Block>,
}

pub fn canonical_bytes(value: &Value) -> Vec<u8> {
    let sorted = sort_value(value);
    serde_json::to_vec(&sorted).expect("canonical json")
}

pub fn hash_value(value: &Value) -> String {
    let mut h = Sha256::new();
    h.update(&canonical_bytes(value));
    hex::encode(h.finalize())
}

fn sort_value(v: &Value) -> Value {
    match v {
        Value::Object(m) => {
            let mut out: BTreeMap<String, Value> = BTreeMap::new();
            for (k, val) in m {
                out.insert(k.clone(), sort_value(val));
            }
            Value::Object(out.into_iter().collect())
        }
        Value::Array(a) => Value::Array(a.iter().map(sort_value).collect()),
        _ => v.clone(),
    }
}

fn reasoning_explicitly_disabled(v: &Value) -> bool {
    match v {
        Value::Object(m) => m.get("enabled") == Some(&Value::Bool(false)),
        _ => false,
    }
}

pub fn normalize_params(body: &Map<String, Value>) -> Result<Map<String, Value>, Error> {
    let params = body
        .get("params")
        .and_then(|v| v.as_object())
        .ok_or_else(|| Error::Pack("model_call missing params".into()))?;
    let mut out = Map::new();
    for key in PARAM_KEYS {
        let v = if params.contains_key(key) {
            params.get(key).cloned().unwrap_or(Value::Null)
        } else {
            Value::Null
        };
        out.insert(key.to_string(), v);
    }
    let reasoning = out.get("reasoning").unwrap();
    if reasoning.is_null() {
        return Err(Error::DidNotRun("reasoning not recorded".into()));
    }
    if !reasoning_explicitly_disabled(reasoning) {
        return Err(Error::DidNotRun("reasoning not explicitly disabled".into()));
    }
    Ok(out)
}

fn block_envelope(data_class: &str, consent_ref: Option<&str>, inner: Value) -> Value {
    let mut m = Map::new();
    m.insert("data_class".into(), Value::String(data_class.to_string()));
    m.insert(
        "consent_ref".into(),
        consent_ref
            .map(|s| Value::String(s.to_string()))
            .unwrap_or(Value::Null),
    );
    m.insert("body".into(), inner);
    Value::Object(m)
}

pub fn leaf_block_from_trace_line(line: &Value) -> Result<(String, Block), Error> {
    let obj = line.as_object().ok_or_else(|| Error::Pack("trace line not an object".into()))?;
    let kind = obj.get("kind").and_then(|v| v.as_str()).unwrap_or("");
    if kind != "model_call" {
        return Err(Error::Pack(format!("unsupported trace kind {:?}", kind)));
    }
    let data_class = obj
        .get("data_class")
        .and_then(|v| v.as_str())
        .ok_or_else(|| Error::Pack("model_call missing data_class".into()))?;
    if DataClass::parse(data_class).is_none() {
        return Err(Error::Pack(format!("unknown data_class {:?}", data_class)));
    }
    let consent_ref = match obj.get("consent_ref") {
        None | Some(Value::Null) => None,
        Some(Value::String(s)) => Some(s.clone()),
        _ => return Err(Error::Pack("consent_ref must be string or null".into())),
    };
    let reply = obj
        .get("reply_raw")
        .ok_or_else(|| Error::Pack("model_call missing reply_raw".into()))?;
    let params = normalize_params(obj)?;
    let mut body = Map::new();
    body.insert("type".into(), Value::String("model_call".into()));
    body.insert("params".into(), Value::Object(params));
    body.insert("reply_raw".into(), reply.clone());
    let envelope = block_envelope(data_class, consent_ref.as_deref(), Value::Object(body));
    let id = hash_value(&envelope);
    let block = Block {
        data_class: data_class.to_string(),
        consent_ref,
        body: envelope.get("body").cloned().unwrap(),
    };
    Ok((id, block))
}

pub fn merkle_parent(left: &str, right: &str) -> String {
    let mut m = Map::new();
    m.insert("type".into(), Value::String("merkle".into()));
    m.insert(
        "children".into(),
        Value::Array(vec![
            Value::String(left.to_string()),
            Value::String(right.to_string()),
        ]),
    );
    hash_value(&Value::Object(m))
}

pub fn merkle_root(leaf_ids: &[String]) -> Result<String, Error> {
    if leaf_ids.is_empty() {
        return Err(Error::Pack("no model_call leaves".into()));
    }
    let mut level = leaf_ids.to_vec();
    while level.len() > 1 {
        let mut next = Vec::new();
        let mut i = 0;
        while i < level.len() {
            let left = &level[i];
            let right = if i + 1 < level.len() {
                &level[i + 1]
            } else {
                &level[i]
            };
            next.push(merkle_parent(left, right));
            i += 2;
        }
        level = next;
    }
    Ok(level[0].clone())
}

pub fn build_merkle_blocks(leaf_ids: &[String]) -> BTreeMap<String, Block> {
    let mut blocks = BTreeMap::new();
    if leaf_ids.is_empty() {
        return blocks;
    }
    let mut level: Vec<String> = leaf_ids.to_vec();
    while level.len() > 1 {
        let mut next = Vec::new();
        let mut i = 0;
        while i < level.len() {
            let left = &level[i];
            let right = if i + 1 < level.len() {
                &level[i + 1]
            } else {
                &level[i]
            };
            let id = merkle_parent(left, right);
            if !blocks.contains_key(&id) {
                let mut body = Map::new();
                body.insert("type".into(), Value::String("merkle".into()));
                body.insert(
                    "children".into(),
                    Value::Array(vec![
                        Value::String(left.clone()),
                        Value::String(right.clone()),
                    ]),
                );
                blocks.insert(
                    id.clone(),
                    Block {
                        data_class: "synthetic".into(),
                        consent_ref: None,
                        body: Value::Object(body),
                    },
                );
            }
            next.push(id);
            i += 2;
        }
        level = next;
    }
    blocks
}

pub fn pack_trace_jsonl<R: BufRead>(reader: R) -> Result<PackedRun, Error> {
    let mut leaves = Vec::new();
    let mut blocks = BTreeMap::new();
    for (lineno, line) in reader.lines().enumerate() {
        let line = line.map_err(|e| Error::Pack(format!("read line {}: {e}", lineno + 1)))?;
        let t = line.trim();
        if t.is_empty() {
            continue;
        }
        let v: Value = serde_json::from_str(t)
            .map_err(|e| Error::Pack(format!("json line {}: {e}", lineno + 1)))?;
        let (id, block) = leaf_block_from_trace_line(&v)?;
        leaves.push(id.clone());
        blocks.insert(id, block);
    }
    let root = merkle_root(&leaves)?;
    blocks.extend(build_merkle_blocks(&leaves));
    Ok(PackedRun {
        root,
        leaves,
        blocks,
    })
}

pub fn export_allowed(data_class: &str, consent_ref: Option<&str>, withdrawn: &HashSet<String>) -> Result<(), Error> {
    match DataClass::parse(data_class) {
        Some(DataClass::Synthetic) | Some(DataClass::Preclinical) => Ok(()),
        Some(DataClass::Clinical) => {
            let cref = consent_ref.ok_or_else(|| Error::ExportRefused("clinical block missing consent_ref".into()))?;
            if withdrawn.contains(cref) {
                return Err(Error::ExportRefused("consent withdrawn".into()));
            }
            Ok(())
        }
        Some(DataClass::HumanSequence) => Err(Error::ExportRefused("human_sequence never exported".into())),
        None => Err(Error::ExportRefused(format!("unknown data_class {:?}", data_class))),
    }
}

pub fn export_gate(packed: &PackedRun, withdrawn: &HashSet<String>) -> Result<(), Error> {
    for id in &packed.leaves {
        let b = packed.blocks.get(id).expect("leaf block");
        export_allowed(&b.data_class, b.consent_ref.as_deref(), withdrawn)?;
    }
    Ok(())
}

fn block_id(block: &Block) -> String {
    let envelope = block_envelope(
        &block.data_class,
        block.consent_ref.as_deref(),
        block.body.clone(),
    );
    hash_value(&envelope)
}

pub fn verify_packed(packed: &PackedRun) -> Result<(), Error> {
    if packed.leaves.is_empty() {
        return Err(Error::Verify("no leaves".into()));
    }
    for id in &packed.leaves {
        let b = packed
            .blocks
            .get(id)
            .ok_or_else(|| Error::Verify(format!("missing leaf block {id}")))?;
        if &block_id(b) != id {
            return Err(Error::Verify(format!("leaf hash mismatch {id}")));
        }
        if b.body.get("type").and_then(|v| v.as_str()) != Some("model_call") {
            return Err(Error::Verify("leaf body type".into()));
        }
    }
    let expected_root = merkle_root(&packed.leaves)?;
    if expected_root != packed.root {
        return Err(Error::Verify("root mismatch".into()));
    }
    verify_merkle_level(&packed.leaves, &packed.root, &packed.blocks)?;
    Ok(())
}

fn verify_merkle_level(leaves: &[String], root: &str, blocks: &BTreeMap<String, Block>) -> Result<(), Error> {
    let mut level = leaves.to_vec();
    while level.len() > 1 {
        let mut next = Vec::new();
        let mut i = 0;
        while i < level.len() {
            let left = &level[i];
            let right = if i + 1 < level.len() {
                &level[i + 1]
            } else {
                &level[i]
            };
            let pid = merkle_parent(left, right);
            let b = blocks
                .get(&pid)
                .ok_or_else(|| Error::Verify(format!("missing merkle node {pid}")))?;
            if hash_value(&b.body) != pid {
                return Err(Error::Verify(format!("merkle hash mismatch {pid}")));
            }
            let children = b
                .body
                .get("children")
                .and_then(|v| v.as_array())
                .ok_or_else(|| Error::Verify("merkle children".into()))?;
            if children.len() != 2
                || children[0].as_str() != Some(left)
                || children[1].as_str() != Some(right)
            {
                return Err(Error::Verify("merkle children order".into()));
            }
            next.push(pid);
            i += 2;
        }
        level = next;
    }
    if level[0] != root {
        return Err(Error::Verify("root level".into()));
    }
    Ok(())
}

pub fn membership_proof(packed: &PackedRun, leaf_id: &str) -> Result<Vec<(String, String, String)>, Error> {
    if !packed.leaves.contains(&leaf_id.to_string()) {
        return Err(Error::Verify("leaf not in run".into()));
    }
    let mut index = packed.leaves.iter().position(|x| x == leaf_id).unwrap();
    let mut level: Vec<String> = packed.leaves.clone();
    let mut proof = Vec::new();
    while level.len() > 1 {
        let sibling = if index % 2 == 0 {
            if index + 1 < level.len() {
                level[index + 1].clone()
            } else {
                level[index].clone()
            }
        } else {
            level[index - 1].clone()
        };
        let left = if index % 2 == 0 {
            level[index].clone()
        } else {
            sibling.clone()
        };
        let right = if index % 2 == 0 {
            sibling.clone()
        } else {
            level[index].clone()
        };
        let parent = merkle_parent(&left, &right);
        proof.push((
            parent.clone(),
            sibling,
            if index % 2 == 0 {
                "right".into()
            } else {
                "left".into()
            },
        ));
        let mut next = Vec::new();
        let mut i = 0;
        while i < level.len() {
            let l = &level[i];
            let r = if i + 1 < level.len() { &level[i + 1] } else { &level[i] };
            next.push(merkle_parent(l, r));
            i += 2;
        }
        index /= 2;
        level = next;
    }
    Ok(proof)
}

pub fn verify_membership(
    leaf_id: &str,
    root: &str,
    proof: &[(String, String, String)],
) -> Result<(), Error> {
    let mut current = leaf_id.to_string();
    for (parent, sibling, side) in proof {
        let (left, right) = if side == "right" {
            (current.clone(), sibling.clone())
        } else {
            (sibling.clone(), current.clone())
        };
        let recomputed = merkle_parent(&left, &right);
        if &recomputed != parent {
            return Err(Error::Verify("proof step mismatch".into()));
        }
        current = parent.clone();
    }
    if current != root {
        return Err(Error::Verify("proof root mismatch".into()));
    }
    Ok(())
}

pub fn load_withdrawn_toml(text: &str) -> Result<HashSet<String>, Error> {
    let mut out = HashSet::new();
    for line in text.lines() {
        let mut rest = line;
        while let Some(start) = rest.find('"') {
            let after = &rest[start + 1..];
            if let Some(end) = after.find('"') {
                let inner = &after[..end];
                if !inner.is_empty() {
                    out.insert(inner.to_string());
                }
                rest = &after[end + 1..];
            } else {
                break;
            }
        }
    }
    Ok(out)
}

/// Paths that must not appear as contiguous string literals in this crate (repo name scan).
pub fn forbidden_path_patterns() -> Vec<&'static str> {
    vec![
        concat!("B", "IO"),
        concat!("/", "workspace"),
        concat!("held", "out"),
        concat!("patient-", "store"),
    ]
}

pub fn write_bundle<W: Write>(writer: &mut W, packed: &PackedRun) -> std::io::Result<()> {
    let mut blocks = Map::new();
    for (k, v) in &packed.blocks {
        blocks.insert(k.clone(), block_envelope(&v.data_class, v.consent_ref.as_deref(), v.body.clone()));
    }
    let bundle = serde_json::json!({
        "root": packed.root,
        "leaves": packed.leaves,
        "blocks": blocks,
    });
    serde_json::to_writer_pretty(&mut *writer, &bundle)?;
    writer.write_all(b"\n")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn sample_call(data_class: &str, consent: Option<&str>) -> Value {
        serde_json::json!({
            "kind": "model_call",
            "data_class": data_class,
            "consent_ref": consent,
            "params": {
                "model": "deepseek/deepseek-v4-pro-0813",
                "temperature": 0,
                "max_tokens": 120,
                "seed": 9001,
                "reasoning": {"enabled": false},
                "response_format": {"type": "json_object"}
            },
            "reply_raw": {"model": "deepseek/deepseek-v4-pro-0813", "choices": [{"message": {"content": "{}"}}]}
        })
    }

    fn pack_one(data_class: &str, consent: Option<&str>) -> PackedRun {
        let line = serde_json::to_string(&sample_call(data_class, consent)).unwrap();
        pack_trace_jsonl(Cursor::new(line)).expect("pack")
    }

    #[test]
    fn clean_synthetic_round_trip() {
        let packed = pack_one("synthetic", None);
        verify_packed(&packed).expect("verify");
        let withdrawn = HashSet::new();
        export_gate(&packed, &withdrawn).expect("export");
        let leaf = &packed.leaves[0];
        let proof = membership_proof(&packed, leaf).expect("proof");
        verify_membership(leaf, &packed.root, &proof).expect("membership");
    }

    #[test]
    fn missing_reasoning_is_did_not_run() {
        let mut v = sample_call("synthetic", None);
        v.as_object_mut().unwrap()["params"]
            .as_object_mut()
            .unwrap()
            .remove("reasoning");
        let line = serde_json::to_string(&v).unwrap();
        let err = pack_trace_jsonl(Cursor::new(line)).unwrap_err();
        assert!(matches!(err, Error::DidNotRun(_)));
    }

    #[test]
    fn reasoning_enabled_is_did_not_run() {
        let mut v = sample_call("synthetic", None);
        v.as_object_mut().unwrap()["params"]
            .as_object_mut()
            .unwrap()
            .insert("reasoning".into(), serde_json::json!({"enabled": true}));
        let line = serde_json::to_string(&v).unwrap();
        assert!(matches!(
            pack_trace_jsonl(Cursor::new(line)).unwrap_err(),
            Error::DidNotRun(_)
        ));
    }

    #[test]
    fn missing_reply_fails_pack() {
        let mut v = sample_call("synthetic", None);
        v.as_object_mut().unwrap().remove("reply_raw");
        let line = serde_json::to_string(&v).unwrap();
        assert!(matches!(
            pack_trace_jsonl(Cursor::new(line)).unwrap_err(),
            Error::Pack(_)
        ));
    }

    #[test]
    fn tampered_leaf_caught() {
        let mut packed = pack_one("synthetic", None);
        let id = packed.leaves[0].clone();
        packed.blocks.get_mut(&id).unwrap().body["params"]["temperature"] = serde_json::json!(1);
        assert!(verify_packed(&packed).is_err());
    }

    #[test]
    fn reordered_leaves_caught() {
        let a = serde_json::to_string(&sample_call("synthetic", None)).unwrap();
        let mut b = sample_call("synthetic", None);
        b.as_object_mut().unwrap()["params"]
            .as_object_mut()
            .unwrap()
            .insert("seed".into(), serde_json::json!(9002));
        let line = format!("{}\n{}", a, serde_json::to_string(&b).unwrap());
        let mut packed = pack_trace_jsonl(Cursor::new(line)).expect("pack");
        packed.leaves.reverse();
        assert!(verify_packed(&packed).is_err());
    }

    #[test]
    fn dropped_leaf_caught() {
        let mut packed = pack_one("synthetic", None);
        packed.leaves.pop();
        assert!(verify_packed(&packed).is_err());
    }

    #[test]
    fn withdrawn_consent_refused() {
        let packed = pack_one("clinical", Some("SYNTH-CONSENT-WITHDRAWN-01"));
        let withdrawn = load_withdrawn_toml("withdrawn = [\"SYNTH-CONSENT-WITHDRAWN-01\"]\n").unwrap();
        assert!(matches!(
            export_gate(&packed, &withdrawn),
            Err(Error::ExportRefused(_))
        ));
    }

    #[test]
    fn missing_consent_refused() {
        let packed = pack_one("clinical", None);
        assert!(matches!(
            export_gate(&packed, &HashSet::new()),
            Err(Error::ExportRefused(_))
        ));
    }

    #[test]
    fn human_sequence_refused() {
        let packed = pack_one("human_sequence", None);
        assert!(matches!(
            export_gate(&packed, &HashSet::new()),
            Err(Error::ExportRefused(_))
        ));
    }

    #[test]
    fn planted_bad_bundle_must_not_verify() {
        let mut packed = pack_one("synthetic", None);
        packed.root = "00".repeat(32);
        if verify_packed(&packed).is_ok() {
            panic!("planted tampered root verified clean — failure");
        }
    }

    #[test]
    fn forbidden_patterns_are_split_literals() {
        let pats = forbidden_path_patterns();
        assert!(pats.iter().any(|p| p.contains("B") && p.contains("IO")));
        let src = std::fs::read_to_string("src/lib.rs").unwrap();
        for p in pats {
            assert!(!src.contains(p));
        }
    }
}
