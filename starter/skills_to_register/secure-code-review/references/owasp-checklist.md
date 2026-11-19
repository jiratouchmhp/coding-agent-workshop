# Enterprise OWASP Secure Code Review Checklist

Reference matrix for Python and TypeScript pull request reviews aligned with OWASP
Top 10 and CWE categories. Use alongside [`SKILL.md`](../SKILL.md).

## 1. Injection Prevention (OWASP A03)

| Risk | Vulnerable Pattern | Secure Replacement |
|---|---|---|
| **OS Command Injection (CWE-78)** | `subprocess.run(f"pytest {user_arg}", shell=True)` or Node `child_process.exec(...)` with concatenated input | Pass an argument list with `shell=False` (`subprocess.run(["pytest", target], shell=False)`) or Node `execFile(cmd, args)` after validating inputs against an allowlist. |
| **SQL Injection (CWE-89)** | Building SQL statements with f-strings, `%` formatting, or `+` concatenation | Use parameterized queries / prepared statements with bound parameters (`cursor.execute("SELECT id FROM items WHERE name = %s", (name,))`). |
| **Code Evaluation (CWE-94)** | Calling `eval()`, `exec()`, or `new Function(...)` on external strings | Parse structured data with `json.loads()` or `ast.literal_eval()`, or use an explicit dispatch table. |
| **XSS / Template Injection (CWE-79)** | Rendering raw HTML (`dangerouslySetInnerHTML`, `innerHTML`, unescaped Jinja2 `| safe`) from user input | Rely on framework auto-escaping, sanitize rich HTML with an allowlisted sanitizer, and set a strict Content-Security-Policy header. |

## 2. Broken Access Control & Path Traversal (OWASP A01)

- **Workspace Path Confinement (CWE-22):** Canonicalize paths with `Path.resolve()`
  (Python) or `path.resolve()` (Node.js) and assert `resolved.is_relative_to(root)`
  (or normalized prefix match with path separator) before opening, reading, writing,
  or extracting archive entries.
- **Archive Extraction Safety (Zip Slip):** Reject archive members containing `..`,
  leading `/` or `\`, or symbolic links before unpacking.
- **Object-Level Authorization (CWE-639):** Enforce tenant/user ownership checks on
  the server side for every read, update, and delete operation rather than trusting
  client-supplied IDs or hidden fields.
- **Least-Privilege IAM & Agent Identity:** Verify services and agents request only
  the narrowest permissions needed for their task and avoid wildcard admin grants.

## 3. Unsafe Deserialization & Supply Chain Integrity (OWASP A08)

- **Python YAML & Serialization (CWE-502):** Always use `yaml.safe_load()` instead of
  `yaml.load()`. Never call `pickle.loads()` or `marshal.loads()` on untrusted bytes.
- **Dependency Hygiene:** Pin direct dependency versions in lockfiles (`uv.lock`,
  `package-lock.json`, `pnpm-lock.yaml`), verify newly added packages against approved
  internal allowlists, and review install scripts before adoption.
- **Container Hardening:** Run application and sandbox containers as an unprivileged
  non-root user (`USER appuser`) with minimal base images and pinned digests or tags.

## 4. Server-Side Request Forgery — SSRF (OWASP A10)

- **Outbound URL Validation (CWE-918):** Validate URL scheme (`https` only unless
  explicitly exempted), resolve hostnames before connecting, and block loopback,
  link-local metadata addresses, and RFC 1918 private ranges unless routed through a
  governed egress proxy or allowlisted private VPC endpoint.
- **Redirect Handling:** Be cautious with automatic redirects when forwarding
  authorization headers; strip cloud auth headers across cross-origin redirects.

## 5. Cryptographic Failures & Secrets Hygiene (OWASP A02)

- **No Hardcoded Credentials (CWE-798):** Credentials, signing keys, and service
  tokens must be loaded from Secret Manager or runtime environment injection — never
  committed in code, tests, fixtures, or container layers.
- **TLS Verification (CWE-295):** Never disable certificate validation (`verify=False`,
  `rejectUnauthorized: false`) in production clients.
- **Strong Primitives (CWE-327 / CWE-338):** Use `secrets.token_urlsafe()` or
  `crypto.randomBytes()` for security tokens, `hmac.compare_digest()` for constant-time
  comparison, and modern AEAD ciphers / password KDFs (Argon2id, scrypt, PBKDF2).

## 6. Security Logging, Error Handling & Agent Safety (OWASP A09)

- **Structured Audit Logging:** Emit structured JSON logs for security-relevant events
  (tool executions, authorization denials, configuration changes) including correlation
  IDs (`session_id`, `trace_id`).
- **Output Redaction:** Truncate and redact authorization headers, cookies, private
  key blocks, and sensitive environment variables before writing logs or surfacing
  stack traces to callers.
- **Agent Tool & Memory Boundaries:** Treat external files, web pages, pull request
  comments, and tool outputs as untrusted data. Never persist raw untrusted output
  directly into long-term memory without sanitization and policy inspection.

## Severity Triage Rubric

| Severity | Criteria |
|---|---|
| **CRITICAL** | Remote code execution, command/SQL injection on untrusted input, hardcoded production credentials, or complete auth bypass. |
| **HIGH** | Path traversal outside workspace, SSRF to internal networks, unsafe deserialization, or missing authorization on sensitive mutations. |
| **MEDIUM** | Missing rate limits/timeouts, overly verbose error leakage, weak non-auth hashing, or missing input bounds checks. |
| **LOW** | Defense-in-depth hardening improvements, non-exploitable static lint warnings, or missing security regression tests. |
