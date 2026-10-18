"""Source-rule tests for frontend health polling resilience, progress debounce flushing, and render scoping.

Enforces:
1. checkHealth in web/lib/engine.ts throws on fetch/network/500 errors, never returning ready:false on failure.
2. refreshHealth in web/lib/store.ts:
   - treats missing fields as ready (only explicit h.ready === false disables input)
   - treats fetch errors as ready (catch blocks set engineReady: true)
   - implements poll backoff loop when explicitly ready === false
   - implements hard cap (e.g. 60s) before enabling anyway
   - provides stopHealthPolling to cancel polling
3. debounced saveProgress in web/lib/store.ts flushes on pagehide, beforeunload, and visibilitychange hidden.
4. ChunkBlock in web/components/Reader.tsx scopes activeGlossId subscription so chunks without the gloss do not re-render.
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_TS = REPO_ROOT / "web" / "lib" / "engine.ts"
STORE_TS = REPO_ROOT / "web" / "lib" / "store.ts"
READER_TSX = REPO_ROOT / "web" / "components" / "Reader.tsx"
COMPOSER_TSX = REPO_ROOT / "web" / "components" / "Composer.tsx"


class FrontendHealthAndProgressRulesTest(unittest.TestCase):
    def test_check_health_does_not_mask_fetch_failures_as_not_ready(self):
        content = ENGINE_TS.read_text(encoding="utf-8")
        # Should NOT return { ok: false, ready: false } on error
        self.assertNotIn("return { ok: false, ready: false }", content)
        # Should throw or propagate when !response.ok
        self.assertIn("throw new Error", content)

    def test_refresh_health_resilience_rules(self):
        content = STORE_TS.read_text(encoding="utf-8")

        # 1. Only explicit ready === false from engine disables input
        self.assertIn("h && h.ready === false", content)

        # 2. Polling backoff mechanism
        self.assertIn("healthPollTimer", content)
        self.assertIn("nextDelay", content)

        # 3. Hard cap (60s) before enabling anyway
        self.assertIn("60000", content)

        # 4. Stop polling on unmount / cleanup
        self.assertIn("stopHealthPolling", content)

        # 5. Fetch error / catch enables input
        self.assertIn("Failed /health fetch", content)

    def test_composer_cleans_up_health_polling_on_unmount(self):
        content = COMPOSER_TSX.read_text(encoding="utf-8")
        self.assertIn("stopHealthPolling", content)

    def test_save_progress_flush_lifecycle_listeners(self):
        content = STORE_TS.read_text(encoding="utf-8")

        # Synchronous flush function
        self.assertIn("function flushProgress", content)
        self.assertIn("localStorage.setItem(\"nekohon-progress\"", content)

        # Event listeners for pagehide, beforeunload, and visibilitychange
        self.assertIn('window.addEventListener("pagehide"', content)
        self.assertIn('window.addEventListener("beforeunload"', content)
        self.assertIn('document.addEventListener("visibilitychange"', content)
        self.assertIn('document.visibilityState === "hidden"', content)

    def test_chunkblock_scopes_active_gloss_subscription(self):
        content = READER_TSX.read_text(encoding="utf-8")
        # Must not do bare `useAsk((s) => s.activeGlossId)` inside ChunkBlock
        self.assertNotIn("const activeGlossId = useAsk((s) => s.activeGlossId);", content)
        # Must scope activeGlossId to whether chunk contains the gloss
        self.assertIn("glosses.some((g) => g.id === activeId)", content)


if __name__ == "__main__":
    unittest.main()
