---
name: secure-code-review
description: >-
  Enterprise OWASP static security audit workflow for Python and TypeScript pull
  requests. Use when reviewing code changes for injection flaws, unsafe subprocess
  or deserialization calls, path traversal, broken access control, or missing input
  validation.
license: Apache-2.0
---

# Secure Code Review Workflow

Perform a structured, evidence-backed security review on modified or targeted source
files inside the active workspace. Do not fabricate findings or report theoretical
issues without citing exact file paths and line numbers observed via file-reading tools.

## Scope & Progressive Disclosure

1. Read the target diff or source files first to identify the language, framework,
   trust boundaries, and external inputs (HTTP handlers, CLI flags, environment
   variables, database queries, subprocess calls, and file paths).
2. Load [`references/owasp-checklist.md`](references/owasp-checklist.md) via
   `load_skill_resource` to verify concrete remediation patterns across OWASP Top 10
   and language-specific Python / TypeScript vulnerability classes.
3. When a local or sandbox execution environment is available, run read-only static
   analysis tools (such as `ruff check` or `bandit -r`) against the target directory
   and correlate automated findings with manual review.

## Audit Sequence

### Step 1: Map Untrusted Inputs & Trust Boundaries
- Enumerate every entry point receiving caller-controlled data (request parameters,
  headers, JSON bodies, file uploads, git/PR metadata, or LLM tool outputs).
- Confirm whether the file executes inside a privileged runtime or an isolated
  sandbox and verify that sensitive operations enforce explicit authorization checks.

### Step 2: Check High-Impact Vulnerability Classes
Inspect modified code paths in priority order (full criteria in
`references/owasp-checklist.md`):
- **Command & SQL Injection:** Flag `subprocess` calls using `shell=True` with
  interpolated input, `os.system`, dynamic `eval`/`exec`, or string-formatted SQL
  queries instead of parameterized statements.
- **Path Traversal & File Access:** Verify user-supplied paths are canonicalized and
  checked against an allowed root directory before reading or writing.
- **Unsafe Deserialization & Dynamic Imports:** Flag untrusted `pickle`, `yaml.load`
  without `SafeLoader`, or unvalidated dynamic module loading.
- **Access Control & SSRF:** Verify server-side authorization on every state-changing
  handler and reject unvalidated outbound URLs targeting internal metadata or
  private network addresses.
- **Secrets & Sensitive Logging:** Verify credentials are sourced from Secret Manager
  or environment configuration rather than hardcoded in source files, and ensure logs
  and error responses redact sensitive headers or tokens.
- **Cryptography & Transport Security:** Reject disabled TLS verification
  (`verify=False`), weak hash algorithms for passwords/signatures, and non-cryptographic
  randomness (`random` instead of `secrets`) for tokens.

### Step 3: Verify & Report Findings
For every confirmed issue, provide a structured entry with:
1. **Severity:** `CRITICAL`, `HIGH`, `MEDIUM`, or `LOW`.
2. **Category:** OWASP / CWE classification (for example, `A03: Injection / CWE-78`).
3. **Location:** Exact file path and line range.
4. **Evidence:** The exact vulnerable code pattern and untrusted data flow.
5. **Minimal Fix:** A surgical patch showing the secure replacement and a unit test
   case that prevents regression.

If no vulnerabilities are found, state clearly which files and vulnerability classes
were inspected and note any residual assumptions (for example, upstream gateway
authentication or container network isolation).
