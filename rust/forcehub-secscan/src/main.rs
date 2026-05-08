use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Debug)]
struct Finding {
    level: &'static str,
    rule: &'static str,
    path: String,
    line: Option<usize>,
    message: String,
}

fn add_finding(
    findings: &mut Vec<Finding>,
    level: &'static str,
    rule: &'static str,
    path: &str,
    line: Option<usize>,
    message: impl Into<String>,
) {
    findings.push(Finding {
        level,
        rule,
        path: path.to_string(),
        line,
        message: message.into(),
    });
}

fn git_tracked_files(root: &Path) -> Vec<String> {
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .arg("ls-files")
        .arg("-z")
        .output()
        .expect("failed to run git ls-files");

    if !output.status.success() {
        eprintln!("ERROR: git ls-files failed");
        std::process::exit(2);
    }

    output
        .stdout
        .split(|b| *b == 0)
        .filter(|chunk| !chunk.is_empty())
        .map(|chunk| String::from_utf8_lossy(chunk).to_string())
        .collect()
}

fn is_comment(line: &str) -> bool {
    let t = line.trim_start();
    t.starts_with('#') || t.starts_with("//")
}

fn strip_export(line: &str) -> &str {
    line.trim_start()
        .strip_prefix("export ")
        .unwrap_or(line.trim_start())
        .trim_start()
}

fn is_auth_disabled_assignment(line: &str) -> bool {
    let t = strip_export(line);
    let compact: String = t.chars().filter(|c| !c.is_whitespace()).collect();

    compact.starts_with("FORCEHUB_AUTH_DISABLED=1")
        || compact.starts_with("FORCEHUB_AUTH_DISABLED='1'")
        || compact.starts_with("FORCEHUB_AUTH_DISABLED=\"1\"")
        || compact.contains("FORCEHUB_AUTH_DISABLED:-1")
        || compact.contains("AUTH_DISABLED:-1")
}

fn is_direct_secret_assignment(line: &str) -> bool {
    let t = strip_export(line);
    let lower = t.to_ascii_lowercase();
    let keys = ["password", "token", "api_key", "apikey", "secret"];

    for key in keys {
        if lower.starts_with(key) {
            let rest = t[key.len()..].trim_start();
            if let Some(value) = rest.strip_prefix('=') {
                let value = value.trim();

                if value.is_empty()
                    || value == "''"
                    || value == "\"\""
                    || value.starts_with('$')
                    || value.contains(":-")
                    || value.contains("${")
                {
                    return false;
                }

                return true;
            }
        }
    }

    false
}

fn scan_path_rules(rel: &str, findings: &mut Vec<Finding>) {
    let p = rel.replace('\\', "/");

    if p == ".env" || p.ends_with("/.env") {
        add_finding(
            findings,
            "ERROR",
            "tracked-env",
            &p,
            None,
            ".env must not be tracked",
        );
    }

    if p.starts_with("data/") || p.starts_with("logs/") {
        add_finding(
            findings,
            "ERROR",
            "tracked-runtime-data",
            &p,
            None,
            "runtime data/logs must not be tracked",
        );
    }

    if p.ends_with("agent_token.txt") || p.ends_with("agents.json") {
        add_finding(
            findings,
            "ERROR",
            "tracked-agent-secret-or-state",
            &p,
            None,
            "agent token/state files must not be tracked",
        );
    }

    if p.contains("/target/") || p.starts_with("target/") || p.ends_with("/target") {
        add_finding(
            findings,
            "ERROR",
            "tracked-rust-build-output",
            &p,
            None,
            "Rust target/ build output must not be tracked",
        );
    }
}

fn scan_content_rules(rel: &str, content: &str, findings: &mut Vec<Finding>) {
    let p = rel.replace('\\', "/");

    for (idx, line) in content.lines().enumerate() {
        if is_comment(line) {
            continue;
        }

        let l = line.trim();

        if is_auth_disabled_assignment(l) {
            add_finding(
                findings,
                "ERROR",
                "auth-disabled-default",
                &p,
                Some(idx + 1),
                "ForceHub auth must not default to disabled",
            );
        }

        if l.contains("0.0.0.0")
            && !p.ends_with(".md")
            && (l.contains("uvicorn")
                || l.contains("host")
                || l.contains("bind")
                || l.contains("listen"))
        {
            add_finding(
                findings,
                "ERROR",
                "public-bind-risk",
                &p,
                Some(idx + 1),
                "ForceHub must stay local-only; avoid binding to 0.0.0.0",
            );
        }

        if l.contains("StrictHostKeyChecking=no") {
            add_finding(
                findings,
                "WARN",
                "weak-ssh-host-key-checking",
                &p,
                Some(idx + 1),
                "StrictHostKeyChecking=no weakens SSH safety",
            );
        }

        if is_direct_secret_assignment(l) {
            add_finding(
                findings,
                "WARN",
                "possible-inline-secret",
                &p,
                Some(idx + 1),
                "possible inline secret/token/password",
            );
        }
    }
}

fn scan_file(root: &Path, rel: &str, findings: &mut Vec<Finding>) -> bool {
    scan_path_rules(rel, findings);

    let full = root.join(rel);

    let metadata = match fs::metadata(&full) {
        Ok(m) => m,
        Err(_) => return false,
    };

    if !metadata.is_file() || metadata.len() > 2 * 1024 * 1024 {
        return false;
    }

    let content = match fs::read_to_string(&full) {
        Ok(c) => c,
        Err(_) => return false,
    };

    scan_content_rules(rel, &content, findings);
    true
}

fn print_findings(findings: &[Finding], scanned: usize, root: &Path) {
    println!("ForceHub SecScan");
    println!("Root: {}", root.display());
    println!("Files scanned: {}", scanned);
    println!("Findings: {}", findings.len());

    if findings.is_empty() {
        println!("OK: no findings");
        return;
    }

    println!();

    for finding in findings {
        match finding.line {
            Some(line) => println!(
                "{}\t{}\t{}:{}\t{}",
                finding.level, finding.rule, finding.path, line, finding.message
            ),
            None => println!(
                "{}\t{}\t{}\t{}",
                finding.level, finding.rule, finding.path, finding.message
            ),
        }
    }
}

fn main() {
    let root = env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));

    let root = fs::canonicalize(&root).unwrap_or_else(|err| {
        eprintln!("ERROR: cannot open root path: {}", err);
        std::process::exit(2);
    });

    let files = git_tracked_files(&root);

    let mut findings = Vec::new();
    let mut scanned = 0usize;

    for rel in files {
        if scan_file(&root, &rel, &mut findings) {
            scanned += 1;
        }
    }

    print_findings(&findings, scanned, &root);

    if findings.iter().any(|f| f.level == "ERROR") {
        std::process::exit(2);
    }
}
