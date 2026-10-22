import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("configure", ROOT / "scripts/configure.py")
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
spec = importlib.util.spec_from_file_location("vulns", ROOT / "scripts/check-vulnerabilities.py")
vulns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vulns)


class ConfigurationTests(unittest.TestCase):
    def test_preserves_unmanaged_settings_and_comments(self):
        source = "# Settings\nMods=mine\nPublic=true\nPublic=true\nMap=Custom;Muldraugh, KY\n"
        result = config.merge(source, {"Public": "false", "Password": "a&b=\\c"})
        self.assertIn("Mods=mine\n", result)
        self.assertIn("# Settings\n", result)
        self.assertEqual(result.count("Public="), 1)
        self.assertIn("Password=a&b=\\c\n", result)

    def test_first_launch_and_explicit_mod_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"DATA_DIR": directory, "SERVER_NAME": "test", "MOD_IDS": ""}
            config.configure(env)
            path = Path(directory) / "Server/test.ini"
            self.assertEqual(path.read_text(), "Mods=\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_rejects_bad_values_without_writing(self):
        for bad in ({"SERVER_NAME": "../escape"}, {"GAME_PORT": "70000"},
                    {"SERVER_PASSWORD": "pass\nPublic=true"}, {"PVP": "yes"},
                    {"GAME_PORT": "16261", "DIRECT_PORT": "16261"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                config.configure(bad)

    def test_vulnerability_policy(self):
        report = {"Results": [{"Vulnerabilities": [
            {"Severity": "HIGH", "FixedVersion": "2"},
            {"Severity": "CRITICAL", "FixedVersion": ""},
            {"Severity": "MEDIUM", "FixedVersion": "2"},
        ]}]}
        self.assertEqual(len(vulns.fixable_findings(report)), 1)
