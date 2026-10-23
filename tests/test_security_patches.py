"""Tests for conservative Trivy-to-APT security patch proposals."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/propose-security-patches.py"
SPEC = importlib.util.spec_from_file_location("propose_security_patches", SCRIPT)
patches = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patches)


def vulnerability(identifier="CVE-2026-1000", package="libdemo", installed="1.0", fixed="2.0", severity="HIGH"):
    return {
        "VulnerabilityID": identifier,
        "PkgName": package,
        "InstalledVersion": installed,
        "FixedVersion": fixed,
        "Severity": severity,
    }


def report(*vulnerabilities, result_class="os-pkgs", result_type="debian"):
    return {"SchemaVersion": 2, "Results": [{
        "Class": result_class, "Type": result_type,
        "Vulnerabilities": list(vulnerabilities),
    }]}


class FakeApt:
    def __init__(self):
        self.inventory = "libdemo\tinstall ok installed\tlibdemo\t1.0\t1.0\tamd64\n"
        self.candidate = "2.0"
        self.source = "libdemo (2.0)"
        self.show_override = None
        self.simulation = "Inst libdemo [1.0] (2.0 Debian:13/stable [amd64])\nConf libdemo (2.0 Debian:13/stable [amd64])\n"
        self.simulation_code = 0
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        command = args[0]
        output, code = "", 0
        if command == "dpkg-query":
            output = self.inventory
        elif args[:2] == ("dpkg", "--validate-thing"):
            code = 0
        elif args[:2] == ("dpkg", "--compare-versions"):
            left, operation, right = args[2:]
            order = {"1.0": 1, "1.5": 2, "2.0": 3, "2.0+b1": 4, "3.0": 5}
            left, right = order[left], order[right]
            code = int(not ({"ge": left >= right, "gt": left > right}[operation]))
        elif args[:2] == ("apt-cache", "policy"):
            output = f"libdemo:\n  Installed: 1.0\n  Candidate: {self.candidate}\n"
        elif args[:2] == ("apt-cache", "show"):
            package = args[2].split("=", 1)[0].split(":", 1)[0]
            architecture = "i386" if args[2].startswith("libdemo:i386") else "amd64"
            output = self.show_override or f"Package: {package}\nVersion: {self.candidate}\nArchitecture: {architecture}\nSource: {self.source}\n"
        elif command == "apt-get":
            output, code = self.simulation, self.simulation_code
        else:
            raise AssertionError(f"unexpected command: {args}")
        return subprocess.CompletedProcess(args, code, output, "")


class SecurityPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.report_path = self.root / "report.json"
        self.manifest_path = self.root / "apt-packages.txt"
        self.status_path = self.root / "status.json"
        self.manifest_path.write_text("# Reviewed manual targets\notherpkg=1.0\n\n" + patches.BEGIN + "\n" + patches.END + "\n", encoding="utf-8")
        self.apt = FakeApt()
        run_patch = mock.patch.object(patches, "run", side_effect=self.apt)
        run_patch.start()
        self.addCleanup(run_patch.stop)

    def propose(self, data):
        self.report_path.write_text(json.dumps(data), encoding="utf-8")
        return patches.propose(self.report_path, self.manifest_path, self.status_path)

    def test_source_minimum_and_manual_entries_are_preserved(self):
        status = self.propose(report(vulnerability()))
        content = self.manifest_path.read_text(encoding="utf-8")
        self.assertEqual(status, {"findings": 1, "actionable": 1, "changed": True, "skipped": []})
        self.assertIn("otherpkg=1.0\n", content)
        self.assertIn("# CVE-2026-1000\nlibdemo>=2.0\n", content)
        self.assertNotIn("libdemo=2.0", content)
        self.assertEqual(json.loads(self.status_path.read_text()), status)
        self.assertTrue(any(call[:3] == ("apt-get", "-s", "--no-install-recommends") for call in self.apt.calls))

    def test_idempotent_and_preserves_prior_guard_without_new_findings(self):
        self.propose(report(vulnerability()))
        first = self.manifest_path.read_text()
        self.assertFalse(self.propose(report(vulnerability()))["changed"])
        self.assertEqual(self.manifest_path.read_text(), first)
        self.assertFalse(self.propose(report())["changed"])
        self.assertEqual(self.manifest_path.read_text(), first)

    def test_new_fix_merges_with_prior_guard_at_highest_version(self):
        self.propose(report(vulnerability()))
        self.apt.candidate = "3.0"
        self.apt.source = "libdemo (3.0)"
        self.apt.simulation = "Inst libdemo [1.0] (3.0 Debian:13/stable [amd64])\n"
        status = self.propose(report(vulnerability(identifier="CVE-2026-2000", fixed="3.0")))
        content = self.manifest_path.read_text()
        self.assertEqual(status["actionable"], 1)
        self.assertEqual(content.count("libdemo>="), 1)
        self.assertIn("# CVE-2026-1000, CVE-2026-2000\nlibdemo>=3.0", content)

    def test_counts_non_apt_findings_but_skips_them(self):
        data = {"SchemaVersion": 2, "Results": [
            report(vulnerability())["Results"][0],
            report(vulnerability("CVE-2026-3000", "npm-package"), result_class="lang-pkgs", result_type="npm")["Results"][0],
        ]}
        status = self.propose(data)
        self.assertEqual(status["findings"], 2)
        self.assertEqual(status["actionable"], 1)
        self.assertEqual(status["skipped"], [{"id": "CVE-2026-3000", "package": "npm-package", "reason": "not-debian-os-package"}])

    def test_skips_invalid_name_without_invoking_apt(self):
        status = self.propose(report(vulnerability(package="libdemo;touch /tmp/bad")))
        self.assertEqual(status["findings"], 1)
        self.assertEqual(status["actionable"], 0)
        self.assertEqual(status["skipped"][0]["reason"], "invalid-package-name")
        self.assertFalse(any(call[0] == "apt-cache" or call[0] == "apt-get" for call in self.apt.calls))

    def test_candidate_source_must_reach_fixed_source_version(self):
        self.apt.source = "libdemo (1.5)"
        status = self.propose(report(vulnerability()))
        self.assertEqual(status["actionable"], 0)
        self.assertEqual(status["skipped"][0]["reason"], "candidate-source-below-fix")

    def test_binary_only_rebuild_uses_source_version(self):
        self.apt.candidate = "2.0+b1"
        self.apt.source = "libdemo (2.0)"
        self.apt.simulation = "Inst libdemo [1.0] (2.0+b1 Debian:13/stable [amd64])\n"
        status = self.propose(report(vulnerability()))
        self.assertEqual(status["actionable"], 1)
        self.assertIn("libdemo>=2.0", self.manifest_path.read_text())
        self.assertNotIn("libdemo>=2.0+b1", self.manifest_path.read_text())

    def test_apt_show_selects_matching_architecture_and_source_stanza(self):
        self.apt.show_override = (
            "Package: libdemo\nVersion: 2.0\nArchitecture: i386\nSource: wrong-source (2.0)\n"
            "Filename: pool/main/l/libdemo/libdemo_2.0_i386.deb\n\n"
            "Package: libdemo\nSource: libdemo (2.0)\nVersion: 2.0\nArchitecture: amd64\n"
            "Maintainer: Debian Maintainers <team@debian.org>\n"
            "Filename: pool/main/l/libdemo/libdemo_2.0_amd64.deb\n"
        )
        status = self.propose(report(vulnerability()))
        self.assertEqual(status["actionable"], 1)

    def test_apt_show_without_source_uses_binary_version(self):
        self.apt.show_override = "Package: libdemo\nVersion: 2.0\nArchitecture: amd64\nFilename: pool/main/l/libdemo/libdemo_2.0_amd64.deb\n"
        status = self.propose(report(vulnerability()))
        self.assertEqual(status["actionable"], 1)

    def test_simulation_failure_prevents_guard(self):
        self.apt.simulation_code = 100
        status = self.propose(report(vulnerability()))
        self.assertEqual(status["actionable"], 0)
        self.assertEqual(status["skipped"][0]["reason"], "apt-simulation-failed")
        self.assertNotIn("libdemo>=", self.manifest_path.read_text())

    def test_manual_target_prevents_conflicting_generated_target(self):
        self.manifest_path.write_text("libdemo=1.0\n" + patches.BEGIN + "\n" + patches.END + "\n")
        status = self.propose(report(vulnerability()))
        self.assertEqual(status["actionable"], 0)
        self.assertEqual(status["skipped"][0]["reason"], "manual-apt-target-exists")
        self.assertEqual(self.manifest_path.read_text().count("libdemo"), 1)

    def test_bare_manual_target_rebuilds_for_verified_fix_without_manifest_change(self):
        content = "libdemo\n" + patches.BEGIN + "\n" + patches.END + "\n"
        self.manifest_path.write_text(content)
        status = self.propose(report(vulnerability()))
        self.assertEqual(status, {"findings": 1, "actionable": 1, "changed": False, "skipped": []})
        self.assertEqual(self.manifest_path.read_text(), content)
        self.assertTrue(any(call[:3] == ("apt-get", "-s", "--no-install-recommends") for call in self.apt.calls))

    def test_bare_manual_target_needs_a_candidate_with_fixed_source(self):
        content = "libdemo\n" + patches.BEGIN + "\n" + patches.END + "\n"
        self.manifest_path.write_text(content)
        self.apt.source = "libdemo (1.5)"
        status = self.propose(report(vulnerability()))
        self.assertEqual(status["actionable"], 0)
        self.assertEqual(status["skipped"][0]["reason"], "candidate-source-below-fix")
        self.assertEqual(self.manifest_path.read_text(), content)

    def test_bare_manual_target_needs_successful_apt_simulation(self):
        content = "libdemo\n" + patches.BEGIN + "\n" + patches.END + "\n"
        self.manifest_path.write_text(content)
        self.apt.simulation_code = 100
        status = self.propose(report(vulnerability()))
        self.assertEqual(status["actionable"], 0)
        self.assertEqual(status["skipped"][0]["reason"], "apt-simulation-failed")
        self.assertEqual(self.manifest_path.read_text(), content)

    def test_ambiguous_multiarch_name_is_not_guessed(self):
        self.apt.inventory = (
            "libdemo:amd64\tinstall ok installed\tlibdemo\t1.0\t1.0\tamd64\n"
            "libdemo:i386\tinstall ok installed\tlibdemo\t1.0\t1.0\ti386\n"
        )
        status = self.propose(report(vulnerability()))
        self.assertEqual(status["actionable"], 0)
        self.assertEqual(status["skipped"][0]["reason"], "package-not-uniquely-installed")

    def test_explicit_foreign_architecture_upgrades_only_that_binary(self):
        self.apt.inventory = (
            "libdemo:amd64\tinstall ok installed\tlibdemo\t1.0\t1.0\tamd64\n"
            "libdemo:i386\tinstall ok installed\tlibdemo\t1.0\t1.0\ti386\n"
        )
        self.apt.simulation = "Inst libdemo:amd64 [1.0] (2.0 Debian:13/stable [amd64])\n"
        finding = vulnerability(package="libdemo:i386")
        status = self.propose(report(finding))
        self.assertEqual(status["actionable"], 0)
        self.apt.simulation = "Inst libdemo:i386 [1.0] (2.0 Debian:13/stable [i386])\n"
        status = self.propose(report(finding))
        self.assertEqual(status["actionable"], 1)
        self.assertIn("libdemo:i386>=2.0", self.manifest_path.read_text())

    def test_malformed_scan_fails_without_mutating_manifest(self):
        original = self.manifest_path.read_text()
        with self.assertRaises(ValueError):
            self.propose({"SchemaVersion": 2, "Results": "not-a-list"})
        with self.assertRaises(ValueError):
            self.propose({"SchemaVersion": 2, "Results": []})
        self.assertEqual(self.manifest_path.read_text(), original)


if __name__ == "__main__":
    unittest.main()
