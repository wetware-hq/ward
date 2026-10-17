use std::fs::File;
use std::io::BufReader;
use std::path::PathBuf;
use ward_evidence::{export_gate, load_withdrawn_toml, pack_trace_jsonl, verify_packed, write_bundle};

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: ward-evidence pack <trace.jsonl> [--withdrawn path]");
        eprintln!("       ward-evidence verify <bundle.json>");
        std::process::exit(2);
    }
    match args[1].as_str() {
        "pack" => {
            let path = PathBuf::from(&args[2]);
            let withdrawn_path = args
                .iter()
                .position(|a| a == "--withdrawn")
                .and_then(|i| args.get(i + 1))
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("../data/consent_withdrawn.toml"));
            let f = File::open(&path).expect("open trace");
            let packed = pack_trace_jsonl(BufReader::new(f)).expect("pack");
            let withdrawn =
                load_withdrawn_toml(&std::fs::read_to_string(withdrawn_path).expect("withdrawn")).expect("withdrawn");
            export_gate(&packed, &withdrawn).expect("export gate");
            write_bundle(&mut std::io::stdout(), &packed).expect("write");
        }
        "verify" => {
            let path = PathBuf::from(&args[2]);
            let v: serde_json::Value =
                serde_json::from_reader(BufReader::new(File::open(path).expect("open"))).expect("json");
            let root = v["root"].as_str().expect("root").to_string();
            let leaves = v["leaves"]
                .as_array()
                .expect("leaves")
                .iter()
                .map(|x| x.as_str().expect("leaf").to_string())
                .collect();
            let mut blocks = std::collections::BTreeMap::new();
            let bmap = v["blocks"].as_object().expect("blocks");
            for (id, env) in bmap {
                blocks.insert(
                    id.clone(),
                    ward_evidence::Block {
                        data_class: env["data_class"].as_str().expect("dc").to_string(),
                        consent_ref: env["consent_ref"].as_str().map(String::from),
                        body: env["body"].clone(),
                    },
                );
            }
            let packed = ward_evidence::PackedRun {
                root,
                leaves,
                blocks,
            };
            verify_packed(&packed).expect("verify");
            println!("ok {}", packed.root);
        }
        _ => {
            eprintln!("unknown command");
            std::process::exit(2);
        }
    }
}
