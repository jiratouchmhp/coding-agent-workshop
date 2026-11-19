#!/usr/bin/env python3
"""Deterministic public documentation & sub-link corpus harvester for the workshop workflow.

Fetches:
  - All 34 user-provided seed URLs (via official .md.txt / adk.dev .md / GitHub raw)
  - Auto-discovered Tier-1 sub-links across Gemini Enterprise Agent Platform,
    Agent Registry, ADK, GKE Agent Sandbox / Agent Substrate, and google/agents-cli
  - Any extra Tier-2 URLs passed on CLI (--extra-urls url1 url2 ...)

Writes normalized markdown files to <corpus_dir>/pages/, provenance to
<corpus_dir>/corpus_manifest.json, and domain reading indexes to <corpus_dir>/INDEX_*.md.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRATCH = Path("./.workshop_scratch")
CORPUS_DIR = SCRATCH / "corpus"
PAGES_DIR = CORPUS_DIR / "pages"

USER_SEED_URLS = [
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-terraform",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/tracing",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/logging",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/monitoring",
    "https://adk.dev/get-started/",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/overview",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/agent-evaluation",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-online",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-offline",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-simulated",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/view-results",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/quality-alerts",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/optimize-agent",
    "https://github.com/google/agents-cli",
    # 14 ADK Agent Architectures, Workflows & ADK 2.0 Graph/Dynamic seed URLs
    "https://adk.dev/agents/",
    "https://adk.dev/agents/managed-agents/",
    "https://adk.dev/agents/service-registration/",
    "https://adk.dev/workflows/",
    "https://adk.dev/workflows/collaboration/",
    "https://adk.dev/agents/workflow-agents/",
    "https://adk.dev/agents/routing/",
    "https://adk.dev/workflows/patterns/",
    "https://adk.dev/graphs/",
    "https://adk.dev/graphs/routes/",
    "https://adk.dev/graphs/data-handling/",
    "https://adk.dev/graphs/human-input/",
    "https://adk.dev/graphs/retry/",
    "https://adk.dev/graphs/dynamic/",
]

# Essential domain sub-links we always ensure are fetched alongside auto-discovered links
CURATED_SUBLINKS = [
    # Skill Registry & Agent Registry & Governance
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry/create-manage",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/agent-registry",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/govern-agent-skills",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/agent-identity-overview",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/topology",
    "https://docs.cloud.google.com/agent-registry/overview",
    "https://docs.cloud.google.com/agent-registry/register-skills",
    # Sandbox deep sub-links (lifecycle, templates, snapshots, BYOC, shell, code exec, VPC-SC, CMEK)
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/custom-containers",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/shell-sandbox-quickstart",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/code-execution-overview",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/code-execution-quickstart",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/manage-sandboxes",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/manage-templates",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/manage-snapshots",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/configure-vpc-sc",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/configure-cmek",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/computer-use",
    # Runtime, Quotas, Revisions, Identity, Sessions, Memory Bank, Feedback
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-locations",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/runtime-contract",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-revisions-and-traffic",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-identity",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-an-adk-agent",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions/manage-with-adk",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions/manage-with-api",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions/iam-conditions",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/setup",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/adk-quickstart",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/api-quickstart",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/generate-memories",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/fetch-memories",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/iam-conditions",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service/manage-with-sdk-or-api",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service/view-with-ui",
    # Optimize sub-links
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/traces",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/manage-metrics",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-agents",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/example-store/overview",
    # GKE Agent Sandbox & Agent Substrate docs (for architecture comparison)
    "https://docs.cloud.google.com/kubernetes-engine/docs/concepts/machine-learning/agent-sandbox",
    "https://docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox",
    "https://docs.cloud.google.com/kubernetes-engine/docs/how-to/how-install-agent-sandbox",
    "https://docs.cloud.google.com/kubernetes-engine/docs/concepts/machine-learning/agent-sandbox-storage",
    "https://docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox-pod-snapshots",
    "https://docs.cloud.google.com/kubernetes-engine/ai-ml/about-agent-substrate",
    "https://docs.cloud.google.com/kubernetes-engine/docs/concepts/machine-learning/agent-workloads",
    # ADK key .md pages
    "https://adk.dev/get-started/index.md",
    "https://adk.dev/get-started/python/index.md",
    "https://adk.dev/get-started/google-cloud/index.md",
    "https://adk.dev/get-started/agents-cli/index.md",
    "https://adk.dev/integrations/code-exec-agent-runtime/index.md",
    "https://adk.dev/integrations/gke-code-executor/index.md",
    "https://adk.dev/integrations/skills-registry/index.md",
    "https://adk.dev/integrations/agent-registry/index.md",
    "https://adk.dev/integrations/environment-toolset/index.md",
    "https://adk.dev/integrations/bashtool/index.md",
    "https://adk.dev/skills/index.md",
    "https://adk.dev/sessions/index.md",
    "https://adk.dev/sessions/session/index.md",
    "https://adk.dev/sessions/memory/index.md",
    "https://adk.dev/deploy/agent-runtime/index.md",
    "https://adk.dev/deploy/agent-runtime/agents-cli/index.md",
    "https://adk.dev/deploy/agent-runtime/deploy/index.md",
    "https://adk.dev/deploy/gke/index.md",
    "https://adk.dev/optimize/index.md",
    # google/agents-cli README + all 7 built-in skill SKILL.md files + lifecycle guide
    "https://raw.githubusercontent.com/google/agents-cli/main/README.md",
    "https://raw.githubusercontent.com/google/agents-cli/main/docs/src/guide/lifecycle.md",
    "https://raw.githubusercontent.com/google/agents-cli/main/docs/src/guide/deployment.md",
    "https://raw.githubusercontent.com/google/agents-cli/main/docs/src/guide/evaluation.md",
    "https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-workflow/SKILL.md",
    "https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-adk-code/SKILL.md",
    "https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-scaffold/SKILL.md",
    "https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-eval/SKILL.md",
    "https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-deploy/SKILL.md",
    "https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-publish/SKILL.md",
    "https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-observability/SKILL.md",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (gemini-workshop-harvester)"}


def canonical_url(url: str) -> str:
    url = url.split("#")[0].split("?")[0].rstrip("/")
    if url.endswith(".md.txt"):
        url = url[: -len(".md.txt")]
    return url


def fetch_url_for(url: str) -> str:
    u = url.split("#")[0]
    if u.startswith("https://docs.cloud.google.com/") and not u.endswith(".md.txt"):
        return u.rstrip("/") + ".md.txt"
    if u == "https://adk.dev/get-started/" or u == "https://adk.dev/get-started":
        return "https://adk.dev/get-started/index.md"
    if u == "https://github.com/google/agents-cli":
        return "https://raw.githubusercontent.com/google/agents-cli/main/README.md"
    if u.startswith("https://adk.dev/") and not u.endswith(".md"):
        return u.rstrip("/") + "/index.md"
    return u


def slugify(url: str) -> str:
    s = re.sub(r"^https?://", "", canonical_url(url))
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s).strip("_")
    return s[:160]


def classify_domain(url: str) -> str:
    u = url.lower()
    if "kubernetes-engine" in u or "gke-code-executor" in u or "/deploy/gke" in u:
        return "06_gke_comparison"
    if "sandbox" in u or "code-exec-agent-runtime" in u:
        return "02_sandbox"
    if "skill-registry" in u or "skills-registry" in u or "agent-registry" in u or "/govern/" in u or "adk.dev/skills" in u:
        return "04_govern"
    if "/optimize/" in u or "adk.dev/optimize" in u or "evaluation" in u or "agents-cli-eval" in u or "agents-cli-observability" in u:
        return "05_optimize"
    if (
        "/scale/runtime/" in u
        or "/scale/sessions" in u
        or "/scale/memory-bank" in u
        or "/scale/feedback-service" in u
        or "agent-quotas" in u
        or "agent-locations" in u
        or "adk.dev/sessions" in u
        or "adk.dev/deploy/agent-runtime" in u
        or "agents-cli-deploy" in u
    ):
        return "03_runtime_state"
    return "01_build"


def fetch_one(url: str) -> dict:
    target = fetch_url_for(url)
    req = urllib.request.Request(target, headers=HEADERS)
    code = -1
    body = ""
    err = ""
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            code = resp.status
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        code = e.code
        err = str(e)
        # Fallback to original URL if .md.txt failed
        if target != url and target.endswith(".md.txt"):
            try:
                req2 = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req2, timeout=25) as resp2:
                    code = resp2.status
                    body = resp2.read().decode("utf-8", errors="replace")
                    target = url
                    err = ""
            except Exception as e2:
                err = f"{err}; fallback: {e2}"
    except Exception as e:
        err = str(e)

    canon = canonical_url(url)
    domain = classify_domain(canon)
    file_path = ""
    headings = []
    sublinks = []
    if code == 200 and body:
        out_file = PAGES_DIR / f"{slugify(canon)}.md"
        header = f"<!-- SOURCE_URL: {canon} | FETCHED_URL: {target} | DOMAIN: {domain} -->\n\n"
        out_file.write_text(header + body, encoding="utf-8")
        file_path = str(out_file)
        headings = re.findall(r"^#{1,3}\s+(.+)$", body, flags=re.M)[:15]
        raw_links = set(re.findall(r"https?://[^\s\)\]>\"']+", body))
        for l in sorted(raw_links):
            l_clean = l.rstrip(".,;:")
            if any(
                d in l_clean
                for d in [
                    "docs.cloud.google.com/gemini-enterprise-agent-platform",
                    "docs.cloud.google.com/agent-registry",
                    "docs.cloud.google.com/kubernetes-engine/docs/concepts/machine-learning/agent-",
                    "docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox",
                    "docs.cloud.google.com/kubernetes-engine/ai-ml/about-agent-substrate",
                    "adk.dev/",
                ]
            ):
                sublinks.append(canonical_url(l_clean))

    return {
        "canonical_url": canon,
        "fetched_url": target,
        "status": code,
        "bytes": len(body),
        "domain": domain,
        "is_seed": canon in {canonical_url(u) for u in USER_SEED_URLS},
        "file": file_path,
        "headings": headings,
        "sublinks": sorted(set(sublinks)),
        "error": err,
    }


def write_domain_indexes(manifest: dict) -> None:
    by_domain: dict[str, list[dict]] = {}
    for entry in manifest["pages"].values():
        if entry["status"] == 200 and entry["file"]:
            by_domain.setdefault(entry["domain"], []).append(entry)

    for domain, entries in sorted(by_domain.items()):
        lines = [f"# Corpus Index: {domain}", "", f"Total verified pages: {len(entries)}", ""]
        for e in sorted(entries, key=lambda x: (not x["is_seed"], x["canonical_url"])):
            tag = "[SEED]" if e["is_seed"] else "[SUBLINK]"
            lines.append(f"- {tag} `{e['canonical_url']}` ({e['bytes']} B)")
            lines.append(f"  - Local file: `{e['file']}`")
            if e["headings"]:
                lines.append(f"  - Top headings: {', '.join(e['headings'][:6])}")
        (CORPUS_DIR / f"INDEX_{domain}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extra-urls", nargs="*", default=[])
    parser.add_argument("--discover-tier1", action="store_true", default=True)
    args = parser.parse_args()

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    manifest_path = CORPUS_DIR / "corpus_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"updated_at": "", "seed_urls": USER_SEED_URLS, "pages": {}}

    # Batch 1: Seeds + Curated + Extra URLs not yet fetched with status 200
    initial_urls = list(dict.fromkeys(USER_SEED_URLS + CURATED_SUBLINKS + args.extra_urls))
    to_fetch = [
        u for u in initial_urls
        if manifest["pages"].get(canonical_url(u), {}).get("status") != 200
    ]

    if to_fetch:
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            for res in pool.map(fetch_one, to_fetch):
                manifest["pages"][res["canonical_url"]] = res

    # Batch 2: Auto-discovered Tier-1 sublinks from the 34 seed docs (capped to relevant doc subpages)
    if args.discover_tier1 and not args.extra_urls:
        tier1 = set()
        for entry in manifest["pages"].values():
            if entry["is_seed"] and entry["status"] == 200:
                for sl in entry["sublinks"]:
                    # Skip huge REST API reference trees unless needed
                    if "/reference/rest/" in sl:
                        continue
                    if manifest["pages"].get(sl, {}).get("status") != 200:
                        tier1.add(sl)
        if tier1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                for res in pool.map(fetch_one, sorted(tier1)):
                    manifest["pages"][res["canonical_url"]] = res

    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_domain_indexes(manifest)

    ok = [p for p in manifest["pages"].values() if p["status"] == 200]
    seeds_ok = [p for p in ok if p["is_seed"]]
    failed = [p for p in manifest["pages"].values() if p["status"] != 200]
    print(f"HARVEST_SUMMARY: total={len(manifest['pages'])} ok={len(ok)} seeds_ok={len(seeds_ok)}/{len(USER_SEED_URLS)} failed={len(failed)}")
    if failed:
        for f in failed[:15]:
            print(f"  FAILED [{f['status']}] {f['canonical_url']} -> {f['error']}")


if __name__ == "__main__":
    main()
