import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_TS = REPO_ROOT / "web" / "lib" / "engine.ts"
STORE_TS = REPO_ROOT / "web" / "lib" / "store.ts"
PERSIST_TS = REPO_ROOT / "web" / "lib" / "persist.ts"
READER_TSX = REPO_ROOT / "web" / "components" / "reader" / "Reader.tsx"
COMPOSER_TSX = REPO_ROOT / "web" / "components" / "reader" / "Composer.tsx"


class FrontendHealthAndProgressRulesTest(unittest.TestCase):
    def test_check_health_does_not_mask_fetch_failures_as_not_ready(self):
        content = ENGINE_TS.read_text(encoding="utf-8")
        self.assertNotIn("return { ok: false, ready: false }", content)
        self.assertIn("throw new Error", content)

    def test_refresh_health_resilience_rules(self):
        content = STORE_TS.read_text(encoding="utf-8")

        self.assertIn("h && h.ready === false", content)

        self.assertIn("healthPollTimer", content)
        self.assertIn("nextDelay", content)

        self.assertIn("60000", content)

        self.assertIn("stopHealthPolling", content)

        self.assertRegex(
            content,
            r"\}\s*catch\s*\{\s*stopHealthPolling\(\);\s*set\(\{\s*engineReady:\s*true\s*\}\);",
        )

    def test_composer_cleans_up_health_polling_on_unmount(self):
        content = COMPOSER_TSX.read_text(encoding="utf-8")
        self.assertIn("stopHealthPolling", content)

    def test_save_progress_flush_lifecycle_listeners(self):
        content = PERSIST_TS.read_text(encoding="utf-8")

        self.assertIn("function flushProgress", content)
        self.assertIn("localStorage.setItem(\"nekohon-progress\"", content)

        self.assertIn('window.addEventListener("pagehide"', content)
        self.assertIn('window.addEventListener("beforeunload"', content)
        self.assertIn('document.addEventListener("visibilitychange"', content)
        self.assertIn('document.visibilityState === "hidden"', content)

    def test_chunkblock_scopes_active_gloss_subscription(self):
        content = READER_TSX.read_text(encoding="utf-8")
        self.assertNotIn("const activeGlossId = useAsk((s) => s.activeGlossId);", content)
        self.assertIn("glosses.some((g) => g.id === activeId)", content)

    def test_engine_url_uses_same_origin_and_no_8000_hardcode(self):
        content = ENGINE_TS.read_text(encoding="utf-8")
        self.assertNotIn('!== "8000"', content)
        self.assertIn('=== "3100"', content)


if __name__ == "__main__":
    unittest.main()
