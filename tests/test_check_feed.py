"""Offline delivery regressions: synthetic data, mocked network and state helpers."""
import copy
import unittest
import urllib.error
from unittest.mock import patch, MagicMock

import check_feed as feed


def article(n):
    return {"title": f"Warhammer 40k test {n}", "link": f"https://example.invalid/{n}", "description": ""}


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(feed.urllib.request, "urlopen")
        self.urlopen = self.network.start()
        self.sleep = patch.object(feed.time, "sleep").start()
        patch.object(feed, "WEBHOOK_URL", "https://example.invalid/webhook").start()
        patch.object(feed, "log_message").start()
        self.addCleanup(patch.stopall)
        self.response = MagicMock()
        self.response.__enter__.return_value.status = 204
        self.urlopen.return_value = self.response

    def test_success(self):
        feed.post_to_discord(article(1), feed.DEFAULT_CONFIG)
        self.assertEqual(self.urlopen.call_count, 1)

    def test_missing_webhook_raises_without_network(self):
        with patch.object(feed, "WEBHOOK_URL", ""):
            with self.assertRaises(ValueError):
                feed.post_to_discord(article(1), feed.DEFAULT_CONFIG)
        self.urlopen.assert_not_called()

    def test_429_exhaustion_raises(self):
        self.urlopen.side_effect = urllib.error.HTTPError("https://example.invalid", 429, "limited", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            feed.post_to_discord(article(1), feed.DEFAULT_CONFIG)
        self.assertEqual(self.urlopen.call_count, feed.MAX_RETRIES)
        self.assertEqual(self.sleep.call_count, feed.MAX_RETRIES - 1)

    def test_429_then_success(self):
        self.urlopen.side_effect = [urllib.error.HTTPError("https://example.invalid", 429, "limited", {}, None), self.response]
        feed.post_to_discord(article(1), feed.DEFAULT_CONFIG)
        self.assertEqual(self.urlopen.call_count, 2)

    def test_network_exhaustion_raises(self):
        self.urlopen.side_effect = urllib.error.URLError("offline")
        with self.assertRaises(urllib.error.URLError):
            feed.post_to_discord(article(1), feed.DEFAULT_CONFIG)
        self.assertEqual(self.urlopen.call_count, feed.MAX_RETRIES)

    def test_500_exhaustion_raises(self):
        self.urlopen.side_effect = urllib.error.HTTPError("https://example.invalid", 500, "failed", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            feed.post_to_discord(article(1), feed.DEFAULT_CONFIG)
        self.assertEqual(self.urlopen.call_count, feed.MAX_RETRIES)


class StateTests(unittest.TestCase):
    def setUp(self):
        patch.dict(feed.os.environ, {"GITHUB_ACTIONS": "false"}).start()
        # Block real HTTP even if a future refactor bypasses our posting mock.
        patch.object(feed.urllib.request, "urlopen", side_effect=AssertionError("No network allowed")).start()
        patch.object(feed, "WEBHOOK_URL", "https://example.invalid/webhook").start()
        patch.object(feed, "log_message").start()
        patch.object(feed.time, "sleep").start()
        self.config = copy.deepcopy(feed.DEFAULT_CONFIG)
        self.config["filter"]["keywords"] = ["warhammer"]
        self.load_config = patch.object(feed, "load_config", return_value=self.config).start()
        self.fetch = patch.object(feed, "fetch_feed", return_value=[article(1)]).start()
        self.seen, self.failed = {}, {}
        self.load_seen = patch.object(feed, "load_seen", side_effect=lambda: dict(self.seen)).start()
        self.load_failed = patch.object(feed, "load_failed", side_effect=lambda: dict(self.failed)).start()
        self.save_seen = patch.object(feed, "save_seen", side_effect=lambda d: setattr(self, "seen", dict(d))).start()
        self.save_failed = patch.object(feed, "save_failed", side_effect=lambda d: setattr(self, "failed", dict(d))).start()
        self.post = patch.object(feed, "post_to_discord").start()
        self.error_post = patch.object(feed, "post_error_to_discord").start()
        self.addCleanup(patch.stopall)
        self.aid = feed.article_id(article(1)["link"])

    def test_missing_configuration_fails_before_fetch_or_state(self):
        with patch.object(feed, "WEBHOOK_URL", "   "):
            with self.assertRaises(SystemExit) as result:
                feed.main()
        self.assertEqual(result.exception.code, 1)
        for mock in (self.load_config, self.fetch, self.load_seen, self.load_failed, self.save_seen, self.save_failed, self.post, self.error_post):
            mock.assert_not_called()

    def test_success_marks_seen_only_after_post(self):
        def check_before(*args):
            self.assertNotIn(self.aid, self.seen)
            self.save_seen.assert_not_called()
        self.post.side_effect = check_before
        feed.main()
        self.assertIn(self.aid, self.seen)
        self.assertNotIn(self.aid, self.failed)

    def test_failure_remains_retryable_then_clears_on_success(self):
        self.post.side_effect = RuntimeError("temporary")
        feed.main()
        self.assertEqual(self.failed[self.aid], 1)
        self.assertNotIn(self.aid, self.seen)
        self.post.side_effect = None
        feed.main()
        self.assertEqual(self.post.call_count, 2)
        self.assertIn(self.aid, self.seen)
        self.assertNotIn(self.aid, self.failed)

    def test_three_failed_runs_terminal_without_false_delivery(self):
        self.post.side_effect = RuntimeError("temporary")
        for _ in range(feed.MAX_POST_FAILURES + 1):
            feed.main()
        self.assertEqual(self.post.call_count, feed.MAX_POST_FAILURES)
        self.assertEqual(self.failed[self.aid], feed.MAX_POST_FAILURES)
        self.assertNotIn(self.aid, self.seen)

    def test_historical_retryable_count_two_is_eligible(self):
        self.failed[self.aid] = 2
        feed.main()
        self.post.assert_called_once()
        self.assertIn(self.aid, self.seen)
        self.assertNotIn(self.aid, self.failed)

    def test_historical_terminal_count_is_not_replayed(self):
        self.failed[self.aid] = feed.MAX_POST_FAILURES
        feed.main()
        self.post.assert_not_called()
        self.save_seen.assert_not_called()

    def test_seen_article_not_replayed(self):
        self.seen[self.aid] = "prior timestamp"
        feed.main()
        self.post.assert_not_called()

    def test_filtered_article_not_posted(self):
        self.fetch.return_value = [{**article(1), "title": "unrelated topic"}]
        feed.main()
        self.post.assert_not_called()

    def test_backlog_oldest_first_capped_and_deduplicated(self):
        self.config["max_post"] = 2
        self.fetch.return_value = [article(3), article(2), article(2), article(1)]
        feed.main()
        self.assertEqual([c.args[0]["link"] for c in self.post.call_args_list], [article(1)["link"], article(2)["link"]])
        self.assertEqual(len(self.seen), 2)

    def test_github_actions_warns_without_preventing_state_persistence(self):
        self.post.side_effect = RuntimeError("temporary")
        with patch.dict(feed.os.environ, {"GITHUB_ACTIONS": "true"}), patch("builtins.print") as output:
            feed.main()
        self.assertEqual(self.failed[self.aid], 1)
        self.save_failed.assert_called_once()
        output.assert_called_once_with("::warning::Discord delivery failed for 1 article(s); review persisted failure counts.")

    def test_one_failure_does_not_lose_other_successes(self):
        self.fetch.return_value = [article(2), article(1)]
        self.post.side_effect = [RuntimeError("temporary"), None]
        feed.main()
        self.assertEqual(self.failed[self.aid], 1)
        self.assertNotIn(self.aid, self.seen)
        self.assertIn(feed.article_id(article(2)["link"]), self.seen)


if __name__ == "__main__":
    unittest.main()
