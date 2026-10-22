"""Reject available fixes for High/Critical findings; retain every finding in JSON."""
import json
import sys


def fixable_findings(report):
    return [
        v
        for result in report.get("Results", [])
        for v in result.get("Vulnerabilities", []) or []
        if v.get("Severity") in {"HIGH", "CRITICAL"} and v.get("FixedVersion")
    ]


if __name__ == "__main__":
    with open(sys.argv[1]) as stream:
        report = json.load(stream)
    if report.get("SchemaVersion") != 2 or not report.get("Results"):
        raise SystemExit("Missing or unsupported vulnerability scan results")
    findings = fixable_findings(report)
    for finding in findings:
        print(f"{finding['VulnerabilityID']}: {finding['PkgName']} "
              f"{finding['InstalledVersion']} -> {finding['FixedVersion']}")
    print(f"Fixable High/Critical findings: {len(findings)}")
    raise SystemExit(bool(findings))
