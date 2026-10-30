import copy
import json
import unittest
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
import check_feed as feed
import official_source as source

NOW = datetime(2026, 10, 30, 21, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / 'fixtures'
CONFIG = {'source':'official','official_urls':[sorted(source.ALLOWED_SOURCES)[0]],
          'source_max_age_days':7,'max_article_age_days':3,'not_before':'2026-10-28'}

def html(name='40k'):
    return (FIXTURES / (name + '.html')).read_text()

def response(text):
    r=MagicMock();r.__enter__.return_value=r
    r.read.return_value=text.encode();r.geturl.return_value=CONFIG['official_urls'][0]
    return r

class ParserTests(unittest.TestCase):
    def test_real_pages_have_dated_articles(self):
        expected={'40k':15,'kill-team':12,'home':18}
        for name,count in expected.items():
            articles=source.parse_official_page(html(name))
            self.assertEqual(len(articles),count)
            self.assertTrue(all(a['published_at'] and a['link'].startswith('https://www.warhammer-community.com/articles/') for a in articles))
    def test_known_current_article(self):
        articles=source.parse_official_page(html())
        article=next(a for a in articles if 'cumo9vbg' in a['link'])
        self.assertEqual(article['published_at'],'2026-10-29T00:00:00+00:00')
        self.assertEqual(article['title'],'The Warhammer 40,000 Updates Update')
    def test_duplicate_scripts_deduplicated(self):
        self.assertEqual(len(source.parse_official_page(html()+html())),15)
    def test_no_articles_and_malformed_transport_fail(self):
        for text in ['<html>No results</html>','<script>self.__next_f.push(bad)</script>']:
            with self.assertRaises(source.SourceError):source.parse_official_page(text)
    def test_invalid_date_fails(self):
        with self.assertRaises(source.SourceError):source.parse_official_page(html().replace('2026-10-29','invalid-date'))
    def test_legacy_identity_preserved(self):
        old='https://www.warhammer-community.com/articles/zcobdkzh/your-first-look-at-15-new-space-marine-detachments'
        self.assertEqual(feed.article_id(old),'ef8e2298376cdd7c921ea49dc74a3600')
        self.assertEqual(feed.article_id(old),feed.article_id(old.replace('/articles/','/en-gb/articles/')+'/?utm_source=x'))
    def test_unrelated_url_not_normalized(self):
        url='https://example.invalid/articles/a/b/?x=1';self.assertEqual(source.canonical_article_url(url),url)
    def test_bounded_window_excludes_history_without_mutation(self):
        articles=source.parse_official_page(html());before=copy.deepcopy(articles)
        selected=source.recent_articles(articles,CONFIG,NOW)
        self.assertTrue(selected);self.assertLess(len(selected),len(articles));self.assertEqual(articles,before)
        self.assertTrue(all(a['published_at'] >= '2026-10-28' for a in selected))

class FetchTests(unittest.TestCase):
    def setUp(self):
        patch.dict(source.os.environ,{"GITHUB_ACTIONS":"false"}).start()
        self.net=patch.object(source.urllib.request,'urlopen').start()
        self.sleep=patch.object(source.time,'sleep').start();self.addCleanup(patch.stopall)
        self.net.return_value=response(html())
    def test_stale_category_warns_even_with_fresh_home(self):
        c={**CONFIG,'official_urls':list(source.ALLOWED_SOURCES)}
        self.net.side_effect=[response(html('home')),response(html().replace('2026-10','2026-08')),response(html('kill-team'))]
        with patch('builtins.print') as output, patch.dict(source.os.environ,{'GITHUB_ACTIONS':'true'}):
            self.assertTrue(source.fetch_official(c,NOW))
        self.assertTrue(any('::warning::Official page may be stale or quiet:' in str(c) for c in output.call_args_list))
    def test_fetch_current(self):
        self.assertEqual(len(source.fetch_official(CONFIG,NOW)),15)
    def test_all_pages_deduplicate(self):
        c={**CONFIG,'official_urls':list(source.ALLOWED_SOURCES)}
        self.assertEqual(len(source.fetch_official(c,NOW)),15);self.assertEqual(self.net.call_count,3)
    def test_stale_source_fails(self):
        with self.assertRaisesRegex(source.SourceError,'stale'):source.fetch_official(CONFIG,NOW+timedelta(days=15))
    def test_future_date_fails(self):
        with self.assertRaisesRegex(source.SourceError,'future'):source.fetch_official(CONFIG,NOW-timedelta(days=100))
    def test_network_retry_then_success(self):
        self.net.side_effect=[urllib.error.URLError('offline'),response(html())]
        self.assertEqual(len(source.fetch_official(CONFIG,NOW)),15);self.assertEqual(self.net.call_count,2)
    def test_network_failure_bounded(self):
        self.net.side_effect=urllib.error.URLError('offline')
        with self.assertRaises(source.SourceError):source.fetch_official(CONFIG,NOW)
        self.assertEqual(self.net.call_count,3)
    def test_empty_source_fail_closed(self):
        self.net.return_value=response('<html>Empty</html>')
        with self.assertRaises(source.SourceError):source.fetch_official(CONFIG,NOW)
    def test_unapproved_source_never_requested(self):
        with self.assertRaises(source.SourceError):source.fetch_official({**CONFIG,'official_urls':['https://example.invalid']},NOW)
        self.net.assert_not_called()
    def test_external_redirect_rejected(self):
        self.net.return_value.geturl.return_value='https://example.invalid/'
        with self.assertRaises(source.SourceError):source.fetch_official(CONFIG,NOW)

class ConfigTests(unittest.TestCase):
    def test_missing_configuration_fails_closed(self):
        with patch.object(feed.os.path,'exists',return_value=False):
            with self.assertRaises(source.SourceError):feed.load_config()
    def test_invalid_json_configuration_fails_closed(self):
        from unittest.mock import mock_open
        with patch.object(feed.os.path,'exists',return_value=True), patch('builtins.open',mock_open(read_data='{bad')):
            with self.assertRaises(source.SourceError):feed.load_config()
    def test_unknown_source_fails_closed(self):
        from unittest.mock import mock_open
        with patch.object(feed.os.path,'exists',return_value=True), patch('builtins.open',mock_open(read_data='{"source":"typo"}')):
            with self.assertRaises(source.SourceError):feed.load_config()

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        patch.object(feed.urllib.request,'urlopen',side_effect=AssertionError('No network')).start()
        patch.object(feed,'utcnow',return_value=NOW).start()
        patch.object(feed,'WEBHOOK_URL','https://example.invalid').start()
        self.config={**copy.deepcopy(feed.DEFAULT_CONFIG),**CONFIG,'max_post':2}
        self.config['filter']['keywords']=['warhammer','space','kill team']
        patch.object(feed,'load_config',return_value=self.config).start()
        self.fetch=patch.object(feed,'fetch_official',return_value=source.parse_official_page(html())).start()
        self.seen={};self.failed={}
        patch.object(feed,'load_seen',return_value=self.seen).start();patch.object(feed,'load_failed',return_value=self.failed).start()
        self.save=patch.object(feed,'save_seen').start();self.savefail=patch.object(feed,'save_failed').start()
        self.post=patch.object(feed,'post_to_discord').start();self.error=patch.object(feed,'post_error_to_discord').start()
        patch.object(feed,'log_message').start();patch.object(feed.time,'sleep').start()
        patch.dict(feed.os.environ,{'GITHUB_ACTIONS':'false'}).start();self.addCleanup(patch.stopall)
    def test_dry_run_no_secret_no_posts_no_state_writes(self):
        with patch.object(feed,'WEBHOOK_URL',''):feed.main(dry_run=True)
        self.post.assert_not_called();self.error.assert_not_called();self.save.assert_not_called();self.savefail.assert_not_called()
        self.assertEqual(self.seen,{})
    def test_source_failure_no_discord_or_state(self):
        self.fetch.side_effect=source.SourceError('stale')
        with self.assertRaises(SystemExit):feed.main()
        self.post.assert_not_called();self.error.assert_not_called();self.save.assert_not_called();self.savefail.assert_not_called()
    def test_success_then_seen_no_replay(self):
        feed.main();self.assertGreater(self.post.call_count,0);self.assertLessEqual(self.post.call_count,2)
        count=self.post.call_count;feed.main();self.assertEqual(count,self.post.call_count)
    def test_retryable_failure_not_seen(self):
        self.post.side_effect=RuntimeError('temporary');feed.main()
        self.assertEqual(self.seen,{});self.assertTrue(self.failed)
        self.post.side_effect=None;feed.main();self.assertTrue(self.seen);self.assertEqual(self.failed,{})

if __name__=='__main__':unittest.main()
