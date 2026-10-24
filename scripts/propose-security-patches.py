#!/usr/bin/env python3
"""Propose reviewable APT source-version guards for fixable Trivy findings.

Run in the image being scanned, after ``apt-get update``. A proposed guard is
only emitted after APT can simulate an upgrade of the installed binary package
to a candidate whose *source* version satisfies the Debian advisory.
"""

import json
import re
import subprocess
import sys
from pathlib import Path


BEGIN = "# BEGIN AUTO-GENERATED SECURITY FIXES"
END = "# END AUTO-GENERATED SECURITY FIXES"
PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?\Z")
VERSION = re.compile(r"[0-9][A-Za-z0-9.+:~_-]*\Z")
ADVISORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
SOURCE = re.compile(r"([a-z0-9][a-z0-9+.-]*)(?: \(([^() ]+)\))?\Z")
GUARD = re.compile(r"([a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?)>=([0-9][A-Za-z0-9.+:~_-]*)\Z")


def run(*args):
    return subprocess.run(args, text=True, capture_output=True, check=False)


def version_cmp(left, operation, right):
    result = run("dpkg", "--compare-versions", left, operation, right)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"dpkg could not compare Debian versions: {result.stderr.strip()}")
    return result.returncode == 0


def valid_version(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        return False
    return run("dpkg", "--validate-version", value).returncode == 0


def read_report(path):
    with path.open(encoding="utf-8") as stream:
        report = json.load(stream)
    if not isinstance(report, dict) or report.get("SchemaVersion") != 2:
        raise ValueError("Trivy report must use schema version 2")
    results = report.get("Results")
    if not isinstance(results, list) or not results:
        raise ValueError("Trivy report has no Results")
    findings = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Trivy result must be an object")
        vulnerabilities = result.get("Vulnerabilities", [])
        if vulnerabilities is None:
            vulnerabilities = []
        if not isinstance(vulnerabilities, list):
            raise ValueError("Trivy Vulnerabilities must be a list")
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                raise ValueError("Trivy vulnerability must be an object")
            if vulnerability.get("Severity") in ("HIGH", "CRITICAL") and vulnerability.get("FixedVersion"):
                findings.append((result, vulnerability))
    return findings


def installed_packages():
    command = run(
        "dpkg-query", "-W",
        "-f=${binary:Package}\t${Status}\t${source:Package}\t${source:Version}\t${Version}\t${Architecture}\n",
    )
    if command.returncode:
        raise RuntimeError(f"cannot query installed packages: {command.stderr.strip()}")
    packages = {}
    for line in command.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) != 6:
            raise ValueError("unexpected dpkg-query package inventory")
        name, status, source_name, source_version, version, architecture = fields
        if status != "install ok installed":
            continue
        if not PACKAGE.fullmatch(name) or not PACKAGE.fullmatch(source_name):
            raise ValueError("unexpected installed package or source name")
        if not valid_version(source_version) or not valid_version(version):
            raise ValueError("unexpected installed package version")
        packages[name] = (source_name, source_version, version, architecture)
    return packages


def resolve_installed(name, packages):
    if name in packages:
        return name
    if ":" in name:
        return None
    matches = [installed for installed in packages if installed.split(":", 1)[0] == name]
    return matches[0] if len(matches) == 1 else None


def apt_candidate(package):
    policy = run("apt-cache", "policy", package)
    if policy.returncode:
        return None
    matches = re.findall(r"^\s*Candidate:\s*(\S+)\s*$", policy.stdout, re.MULTILINE)
    return matches[0] if len(matches) == 1 and valid_version(matches[0]) else None


def apt_source(package, candidate, installed_architecture):
    show = run("apt-cache", "show", f"{package}={candidate}")
    if show.returncode:
        return None
    source_versions = set()
    for stanza in re.split(r"\n\s*\n", show.stdout):
        fields = {}
        for line in stanza.splitlines():
            if line and not line[0].isspace() and ":" in line:
                key, value = line.split(":", 1)
                fields[key] = value.strip()
        if fields.get("Package") != package.split(":", 1)[0] or fields.get("Version") != candidate:
            continue
        if fields.get("Architecture") != installed_architecture:
            continue
        source = fields.get("Source")
        if source is None:
            source_name, source_version = fields["Package"], candidate
        else:
            parsed = SOURCE.fullmatch(source)
            if not parsed:
                return None
            source_name, source_version = parsed.group(1), parsed.group(2) or candidate
        if not valid_version(source_version):
            return None
        source_versions.add((source_name, source_version))
    return next(iter(source_versions)) if len(source_versions) == 1 else None


def simulates_upgrade(package, installed_version, candidate):
    simulation = run(
        "apt-get", "-s", "--no-install-recommends", "--only-upgrade", "--no-remove",
        "install", f"{package}={candidate}",
    )
    if simulation.returncode or re.search(r"^(?:Remv|Purg)\s", simulation.stdout, re.MULTILINE):
        return False
    if "DOWNGRADED" in simulation.stdout.upper():
        return False
    target_found = False
    for line in simulation.stdout.splitlines():
        if not line.startswith("Inst "):
            continue
        match = re.match(r"Inst\s+(\S+)(?:\s+\[([^]]+)\])?\s+\((\S+)", line)
        if not match:
            return False
        name, old_version, new_version = match.groups()
        if old_version and not version_cmp(new_version, "ge", old_version):
            return False
        matches_package = name == package or (
            ":" not in package and name.split(":", 1)[0] == package
        )
        if not matches_package and ":" in package:
            # dpkg-query qualifies Multi-Arch packages even for the native
            # architecture; APT may use a bare name plus [architecture].
            base, architecture = package.split(":", 1)
            apt_architecture = re.search(r"\[([a-z0-9]+)\]\)\s*$", line)
            matches_package = (
                name == base and apt_architecture is not None
                and apt_architecture.group(1) == architecture
            )
        if matches_package and new_version == candidate:
            target_found = True
    return target_found and version_cmp(candidate, "gt", installed_version)


def split_manifest(content):
    lines = content.splitlines(keepends=True)
    begins = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == BEGIN]
    ends = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == END]
    if not begins and not ends:
        return content, None, ""
    if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
        raise ValueError("APT manifest has malformed generated section markers")
    return "".join(lines[:begins[0]]), "".join(lines[begins[0] + 1:ends[0]]), "".join(lines[ends[0] + 1:])


def old_guards(section):
    guards = {}
    advisories = {}
    current_ids = set()
    for raw in section.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            ids = [item.strip() for item in line[2:].split(",")]
            if not ids or any(not ADVISORY.fullmatch(item) for item in ids):
                raise ValueError("invalid generated advisory comment")
            current_ids.update(ids)
            continue
        match = GUARD.fullmatch(line)
        if not match or not valid_version(match.group(2)):
            raise ValueError("invalid generated APT guard")
        package, version = match.groups()
        if package in guards:
            if version_cmp(version, "gt", guards[package]):
                guards[package] = version
        else:
            guards[package] = version
        advisories.setdefault(package, set()).update(current_ids)
        current_ids.clear()
    if current_ids:
        raise ValueError("generated advisory comment lacks an APT guard")
    return guards, advisories


def manual_packages(prefix, suffix):
    packages = {}
    for line in (prefix + suffix).splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(
            r"([a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?)(?:(>=|=)[A-Za-z0-9.+:~_-]+)?",
            line,
        )
        if match:
            packages.setdefault(match.group(1), set()).add(match.group(2) or "bare")
    return packages


def render_manifest(prefix, section, suffix, guards, advisories):
    generated = []
    for package in sorted(guards):
        ids = sorted(advisories.get(package, ()))
        if ids:
            generated.append("# " + ", ".join(ids) + "\n")
        generated.append(f"{package}>={guards[package]}\n")
    if section is None:
        if not generated:
            return prefix
        separator = "\n" if prefix and not prefix.endswith("\n\n") else ""
        return prefix + separator + BEGIN + "\n" + "".join(generated) + END + "\n"
    return prefix + BEGIN + "\n" + "".join(generated) + END + "\n" + suffix


def propose(report_path, manifest_path, status_path):
    findings = read_report(report_path)
    original = manifest_path.read_text(encoding="utf-8")
    prefix, section, suffix = split_manifest(original)
    guards, advisories = old_guards(section or "")
    manual = manual_packages(prefix, suffix)
    packages = installed_packages() if findings else {}
    skipped = []
    eligible = {}
    bare_manual = set()

    for result, finding in findings:
        name = finding.get("PkgName")
        identifier = finding.get("VulnerabilityID")
        fixed = finding.get("FixedVersion")
        label = {"id": str(identifier or ""), "package": str(name or "")}

        def skip(reason):
            skipped.append({**label, "reason": reason})

        if result.get("Class") != "os-pkgs" or result.get("Type") != "debian":
            skip("not-debian-os-package")
            continue
        if not isinstance(name, str) or not PACKAGE.fullmatch(name):
            skip("invalid-package-name")
            continue
        if not isinstance(identifier, str) or not ADVISORY.fullmatch(identifier):
            skip("invalid-advisory-id")
            continue
        if not valid_version(fixed):
            skip("invalid-fixed-source-version")
            continue
        resolved = resolve_installed(name, packages)
        if resolved is None:
            skip("package-not-uniquely-installed")
            continue
        manual_kinds = manual.get(resolved, set())
        # An unqualified manual target may refer to another architecture.
        # Only the exact installed package name can be trusted as a bare target.
        if ":" in resolved and resolved.split(":", 1)[0] in manual:
            manual_kinds = manual_kinds | {"other-architecture"}
        if manual_kinds and manual_kinds != {"bare"}:
            skip("manual-apt-target-exists")
            continue
        if manual_kinds == {"bare"}:
            bare_manual.add(resolved)
        source_name, installed_source, installed_binary, architecture = packages[resolved]
        reported_installed = finding.get("InstalledVersion")
        if reported_installed not in (installed_binary, installed_source):
            skip("installed-version-mismatch")
            continue
        if version_cmp(installed_source, "ge", fixed):
            skip("source-already-fixed")
            continue
        candidate = apt_candidate(resolved)
        if candidate is None or not version_cmp(candidate, "gt", installed_binary):
            skip("no-newer-apt-candidate")
            continue
        source = apt_source(resolved, candidate, architecture)
        if source is None or source[0] != source_name:
            skip("candidate-source-unavailable-or-mismatched")
            continue
        if not version_cmp(source[1], "ge", fixed):
            skip("candidate-source-below-fix")
            continue
        eligible.setdefault(resolved, []).append((identifier, fixed, installed_binary, candidate))

    actionable = 0
    for package, proposals in eligible.items():
        installed_binary, candidate = proposals[0][2:]
        if not simulates_upgrade(package, installed_binary, candidate):
            skipped.extend(
                {"id": identifier, "package": package, "reason": "apt-simulation-failed"}
                for identifier, _, _, _ in proposals
            )
            continue
        actionable += len(proposals)
        if package in bare_manual:
            # The reviewed bare target already requests the newest APT version.
            # Rebuild to use that fix without inserting a duplicate target.
            continue
        for identifier, fixed, _, _ in proposals:
            if package not in guards or version_cmp(fixed, "gt", guards[package]):
                guards[package] = fixed
            advisories.setdefault(package, set()).add(identifier)

    updated = render_manifest(prefix, section, suffix, guards, advisories)
    changed = updated != original
    if changed:
        manifest_path.write_text(updated, encoding="utf-8")
    status = {
        "findings": len(findings),
        "actionable": actionable,
        "changed": changed,
        "skipped": sorted(skipped, key=lambda item: (item["package"], item["id"], item["reason"])),
    }
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return status


def main(argv):
    if len(argv) != 4:
        raise SystemExit("usage: propose-security-patches.py REPORT MANIFEST STATUS_JSON")
    try:
        propose(*(Path(path) for path in argv[1:]))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"security patch proposal failed: {error}") from error


if __name__ == "__main__":
    main(sys.argv)
