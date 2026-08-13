# Security Policy

## Reporting Vulnerabilities

If you discover a potential security vulnerability in iScan, please do NOT create a public issue.
Instead, report it directly to the maintainers at `security@chumafox.org` or open a private security advisory on GitHub.

## Security Controls

- HTML report rendering uses Jinja2 autoescaping (`select_autoescape(['html', 'xml', 'j2'])`) to prevent XSS.
- Atomic report file writing (`NamedTemporaryFile` + `os.replace`).
- Transport provenance tracking and fail-soft per-service collection.
