"""Exercise launch arguments and signal handling with a local console server."""
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        for name in ("server", "data", "run", "home", "bin", "seed"):
            (self.base / name).mkdir()
        # macOS has no util-linux setsid. Use the same POSIX primitive for tests.
        shim = self.base / "bin/setsid"
        shim.write_text("#!/usr/bin/env python3\nimport os,sys\nos.setsid()\nos.execvp(sys.argv[1],sys.argv[1:])\n")
        shim.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.base / "home"),
                        SERVER_DIR=str(self.base / "server"), DATA_DIR=str(self.base / "data"),
                        RUN_DIR=str(self.base / "run"), STEAMCMD_DIR=str(self.base / "steamcmd"),
                        STEAMCMD_SEED=str(self.base / "seed"), SERVER_NAME="test", ADMIN_PASSWORD="bootstrap secret",
                        UPDATE_ON_START="false", SHUTDOWN_TIMEOUT="3", MIN_MEMORY="1g", MAX_MEMORY="4g",
                        CONFIGURE_SCRIPT=str(ROOT / "scripts/configure.py"),
                        PATH=str(self.base / "bin") + os.pathsep + os.environ["PATH"])
        (self.base / "server/start-server.sh").write_text(
            '#!/usr/bin/env bash\n'
            'printf "%s\\n" "$@" > "$DATA_DIR/args"\n'
            'while IFS= read -r line; do\n'
            '  printf "%s\\n" "$line" >> "$DATA_DIR/commands"\n'
            '  [[ "$line" == quit ]] && exit 0\n'
            'done\n'
        )

    def launch(self):
        log = open(self.base / "log", "w+")
        self.addCleanup(log.close)
        process = subprocess.Popen(["bash", str(ROOT / "scripts/entrypoint.sh")],
                                   env=self.env, stdout=log, stderr=log)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        for _ in range(100):
            if (self.base / "data/args").exists():
                return process
            if process.poll() is not None:
                self.fail((self.base / "log").read_text())
            time.sleep(0.05)
        self.fail("Mock launcher did not start")

    def stop(self, process):
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=10), 0, (self.base / "log").read_text())
        self.assertEqual((self.base / "data/commands").read_text(), "save\nquit\n")

    def test_bootstrap_and_graceful_shutdown(self):
        process = self.launch()
        args = (self.base / "data/args").read_text().splitlines()
        self.assertEqual(args[:3], ["-Xms1g", "-Xmx4g", "--"])
        self.assertEqual(args[-2:], ["-adminpassword", "bootstrap secret"])
        self.stop(process)

    def test_existing_database_omits_bootstrap_password(self):
        (self.base / "data/db").mkdir()
        (self.base / "data/db/test.db").touch()
        self.env.pop("ADMIN_PASSWORD")
        process = self.launch()
        self.assertNotIn("-adminpassword", (self.base / "data/args").read_text())
        self.stop(process)

    def test_download_arguments_and_beta_branch(self):
        self.env.update(UPDATE_ON_START="true", STEAM_BRANCH="unstable")
        steam = self.base / "seed/steamcmd.sh"
        steam.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$DATA_DIR/steam-args"\n')
        steam.chmod(0o755)
        process = self.launch()
        args = (self.base / "data/steam-args").read_text().splitlines()
        self.assertEqual(args, ["+force_install_dir", self.env["SERVER_DIR"], "+login", "anonymous",
                                "+app_update", "380870", "-beta", "unstable", "validate", "+quit"])
        self.stop(process)
