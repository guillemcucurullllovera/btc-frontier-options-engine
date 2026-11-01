# Security policy

## Reporting a vulnerability

Do not open a public issue for a vulnerability.

Use GitHub private vulnerability reporting on this repository. If that is unavailable, contact the
maintainer through the address in `CITATION.cff`.

Include:

- a minimal reproduction;
- the affected version or commit;
- the impact and the conditions required;
- any suggested mitigation.

## Response

- Acknowledgement within 72 hours.
- Assessment and a mitigation plan within 14 days.
- A fix or a documented mitigation within 30 days for a confirmed high-severity issue.

## Scope

This project is research software. It is not a production service and does not process personal data.
The most relevant risks are:

- arbitrary code execution through a malicious input file;
- a dependency compromise;
- a denial of service through an unbounded allocation;
- a published result that is wrong in a way that could mislead.

The last one is treated as a correctness bug, not a security vulnerability, but it is handled with the
same urgency.

## Out of scope

- Vulnerabilities in third-party dependencies: report them upstream, and open an issue here so the pin
  can be updated.
- Issues that require a compromised local environment.
- Social engineering.
