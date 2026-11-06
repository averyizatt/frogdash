"""Eight-hour device logins renew privately; old login dates do not follow a reconnect."""
import asyncio
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock

from hardware.frogdash.github_link import GitHubLink, RefreshRefused, refresh_login, write_login
from tools.frogdash_upload import GitHub


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'log-upload.json'
        self.link = GitHubLink(self.folder.name, client_id='app-id', wall=lambda: 1000)
        self.link.save('old-access', 'owner', {'access_token': 'old-access', 'refresh_token': 'old-refresh',
                                            'expires_in': 28800, 'refresh_token_expires_in': 15897600})
        self.config = json.loads(self.path.read_text())
        self.answer = {'access_token': 'new-access', 'refresh_token': 'new-refresh', 'expires_in': 28800,
                       'refresh_token_expires_in': 15897600}

    def test_refresh_token_saved_privately_but_status_has_no_secrets(self):
        self.assertEqual(self.config['expires_at'], 29800)
        self.assertEqual(self.config['refresh_token'], 'old-refresh')
        status = self.link.status()
        self.assertTrue(status['renewable'])
        self.assertEqual(status['expires'], '1970-01-01T08:16:40Z')
        for secret in ('old-access', 'old-refresh'):
            self.assertNotIn(secret, json.dumps(status))
        if os.name == 'posix':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_renew_only_when_due_and_save_both_rotated_tokens(self):
        post = Mock(return_value=self.answer)
        unchanged = refresh_login(self.path, self.config, post=post, wall=lambda: 2000)
        self.assertEqual(unchanged, self.config)
        post.assert_not_called()
        previous = self.path.stat()
        updated = refresh_login(self.path, self.config, post=post, wall=lambda: 29600)
        self.assertEqual(post.call_args.args[1], {'client_id': 'app-id', 'grant_type': 'refresh_token',
                                                'refresh_token': 'old-refresh'})
        self.assertEqual(updated['token'], 'new-access')
        self.assertEqual(updated['refresh_token'], 'new-refresh')
        self.assertEqual(updated['expires_at'], 58400)
        self.assertEqual(updated['login_id'], self.config['login_id'])
        self.assertEqual(json.loads(self.path.read_text()), updated)
        self.assertEqual((self.path.stat().st_uid, self.path.stat().st_gid), (previous.st_uid, previous.st_gid))

    def test_network_failure_keeps_the_login_and_invalid_refresh_requests_reconnect(self):
        before = self.path.read_bytes()
        with self.assertRaises(urllib.error.URLError):
            refresh_login(self.path, self.config, force=True, post=Mock(side_effect=urllib.error.URLError('offline')))
        self.assertEqual(self.path.read_bytes(), before)
        for response in ({'error': 'bad_refresh_token'}, {'error': 'expired_token'}):
            with self.assertRaises(RefreshRefused):
                refresh_login(self.path, self.config, force=True, post=Mock(return_value=response))
        error = urllib.error.HTTPError('https://github.com/login/oauth/access_token', 400, 'Bad Request', {},
                                       io.BytesIO(b'{"error":"bad_refresh_token"}'))
        with self.assertRaises(RefreshRefused):
            refresh_login(self.path, self.config, force=True, post=Mock(side_effect=error))
        self.assertEqual(self.path.read_bytes(), before)

    def test_incomplete_or_temporary_answer_does_not_replace_credentials(self):
        for answer in ({'access_token': 'partial'}, {'error': 'temporarily_unavailable'}):
            with self.assertRaises(RuntimeError):
                refresh_login(self.path, self.config, force=True, post=Mock(return_value=answer))
            self.assertEqual(json.loads(self.path.read_text()), self.config)

    def test_disconnecting_or_reconnecting_during_renewal_is_not_undone(self):
        def reconnect(url, fields):
            self.link.save('replacement', 'owner')
            return self.answer
        with self.assertRaisesRegex(RuntimeError, 'connection changed'):
            refresh_login(self.path, self.config, force=True, post=reconnect)
        self.assertEqual(json.loads(self.path.read_text())['token'], 'replacement')
        self.path.unlink()
        with self.assertRaisesRegex(RuntimeError, 'connection changed'):
            write_login(self.path, self.config, expected_token='old-access')
        self.assertFalse(self.path.exists())

    def test_old_upload_expiry_does_not_follow_a_new_connection(self):
        (self.path.parent / 'upload-status.json').write_text(json.dumps({
            'login': {'expires': '2026-11-07 04:37:08 UTC', 'login_id': self.config['login_id']}}))
        self.link.save('replacement', 'owner')
        self.assertIsNone(self.link.status()['expires'])
        self.assertFalse(self.link.status()['renewable'])

    def test_api_renews_on_401_once_and_replays_the_request(self):
        calls = []
        class Opener:
            def open(inner, request, timeout):
                calls.append((request.get_header('Authorization'), request.data))
                if len(calls) == 1:
                    raise urllib.error.HTTPError(request.full_url, 401, 'Unauthorized', {}, io.BytesIO(b'{}'))
                response = io.BytesIO(b'{"ok":true}')
                response.status, response.headers = 200, {}
                return response
        renew = Mock(side_effect=['old-access', 'new-access'])
        github = GitHub('owner/repo', 'old-access', opener=Opener(), renew=renew)
        self.assertEqual(github.call('PUT', 'https://api.github.com/repos/owner/repo/contents/test', {'content': 'YQ=='}),
                         (200, {'ok': True}))
        self.assertEqual([args.args[0] for args in renew.call_args_list], [False, True])
        self.assertEqual([auth for auth, _ in calls], ['Bearer old-access', 'Bearer new-access'])
        self.assertEqual(calls[0][1], calls[1][1])


class DeviceFlowRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_flow_keeps_the_full_token_response(self):
        with tempfile.TemporaryDirectory() as folder:
            answer = {'access_token': 'device-access', 'refresh_token': 'device-refresh', 'expires_in': 28800}
            post = Mock(side_effect=[{'device_code': 'd', 'user_code': 'CODE', 'expires_in': 900}, answer])
            link = GitHubLink(folder, client_id='app', post=post, user=lambda token: {'login': 'owner'},
                              sleep=lambda s: asyncio.sleep(0), wall=lambda: 1000)
            await link.connect()
            await link.task
            saved = json.loads(link.config_path.read_text())
            self.assertEqual(saved['refresh_token'], 'device-refresh')
            self.assertEqual(saved['expires_at'], 29800)
            self.assertTrue(link.status()['renewable'])


if __name__ == '__main__':
    unittest.main()
