"""Connect the dash to GitHub with a short code, so reports upload after every update
without a token being copied anywhere (GitHub's device flow).

The driver presses Connect GitHub (Dash management > Software & power). The dash asks
GitHub for a code and shows it; on a phone the owner opens github.com/login/device,
types the code and presses Authorize. The dash waits for that, then saves the access it
was given in log-upload.json (readable only by the dash and root), where
tools/frogdash_upload.py finds it. Disconnect deletes it; it can also be revoked on
GitHub (Settings > Applications).

This needs the client ID of the owner's own GitHub OAuth app with device flow switched on
(a public ID, not a secret): CLIENT_ID below, or FROGDASH_GITHUB_CLIENT_ID.
The access asked for is public_repo: write to the owner's public repositories.
"""
import asyncio
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

CLIENT_ID = 'Ov23li7DGiineMBNPBYy'   # The owner's Frogdash OAuth app (device flow on); public, not a secret
REPO = 'averyizatt/frogdash'
SCOPE = 'public_repo'
CODE_URL = 'https://github.com/login/device/code'
TOKEN_URL = 'https://github.com/login/oauth/access_token'
USER_URL = 'https://api.github.com/user'


def post_form(url, fields, timeout=15):
    request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method='POST',
                                     headers={'Accept': 'application/json', 'User-Agent': 'fox-body-dash'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def get_user(token, timeout=15):
    request = urllib.request.Request(USER_URL, headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                                                        'User-Agent': 'fox-body-dash'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


class GitHubLink:
    def __init__(self, folder, client_id=None, post=post_form, user=get_user, sleep=asyncio.sleep, wall=time.time):
        self.folder = Path(folder)
        self.client_id = client_id if client_id is not None else os.environ.get('FROGDASH_GITHUB_CLIENT_ID', CLIENT_ID)
        self.post, self.user, self.sleep, self.wall = post, user, sleep, wall
        self.link = {'state': 'idle'}
        self.task = None

    @property
    def config_path(self):
        return self.folder / 'log-upload.json'

    def read(self, name):
        try:
            return json.loads((self.folder / name).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def status(self):
        config = self.read('log-upload.json')
        config = config if isinstance(config, dict) else {}
        last = self.read('upload-status.json')
        last = {k: v for k, v in (last or {}).items() if k in ('time', 'state', 'message')} if isinstance(last, dict) else {}
        reports = self.folder / 'reports'
        held = sum(1 for p in reports.iterdir() if p.is_dir()) if reports.is_dir() else 0
        link = dict(self.link)
        if link.get('state') == 'waiting' and self.wall() > link.get('expires_at', 0):
            link = self.link = {'state': 'failed', 'message': 'The code ran out before it was entered. Press Connect GitHub for a new one'}
        return {'configured': bool(config.get('token')), 'repo': config.get('repo') or None, 'account': config.get('account'),
                'ready': bool(self.client_id), 'last': last or None, 'held': held, 'link': link}

    def save(self, token, account):
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'repo': REPO, 'token': token, 'account': account, 'via': 'device code'}), encoding='utf-8')
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.config_path)

    def disconnect(self):
        if self.task:
            self.task.cancel()
        self.config_path.unlink(missing_ok=True)
        self.link = {'state': 'idle'}

    async def connect(self):
        """Ask GitHub for a code, then wait in the background for it to be entered."""
        if not self.client_id:
            raise ValueError('This dash has no GitHub app ID yet: see hardware/frogdash/github_link.py')
        if self.task and not self.task.done():
            return self.link
        try:
            answer = await asyncio.to_thread(self.post, CODE_URL, {'client_id': self.client_id, 'scope': SCOPE})
        except (OSError, ValueError, urllib.error.URLError) as error:
            self.link = {'state': 'failed', 'message': f'Could not reach GitHub: {getattr(error, "reason", error)}. Join Wi-Fi with internet first'}
            return self.link
        if not answer.get('user_code') or not answer.get('device_code'):
            self.link = {'state': 'failed', 'message': f"GitHub said: {answer.get('error_description') or answer.get('error') or 'no code'}"}
            return self.link
        self.link = {'state': 'waiting', 'code': answer['user_code'], 'url': answer.get('verification_uri', 'https://github.com/login/device'),
                     'expires_at': self.wall() + int(answer.get('expires_in', 900))}
        self.task = asyncio.create_task(self.wait(answer['device_code'], int(answer.get('interval', 5))))
        return self.link

    async def wait(self, device_code, interval):
        fields = {'client_id': self.client_id, 'device_code': device_code, 'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'}
        while self.link.get('state') == 'waiting' and self.wall() <= self.link.get('expires_at', 0):
            await self.sleep(interval)
            try:
                answer = await asyncio.to_thread(self.post, TOKEN_URL, fields)
            except (OSError, ValueError, urllib.error.URLError):
                continue   # The Wi-Fi blinked: keep waiting while the code is good.
            error = answer.get('error')
            if error == 'authorization_pending':
                continue
            if error == 'slow_down':
                interval = int(answer.get('interval', interval + 5))
                continue
            if error or not answer.get('access_token'):
                self.link = {'state': 'failed', 'message': 'Authorize was declined on GitHub' if error == 'access_denied'
                             else 'The code ran out before it was entered. Press Connect GitHub for a new one' if error == 'expired_token'
                             else f'GitHub said: {answer.get("error_description") or error}'}
                return
            token = answer['access_token']
            try:
                account = (await asyncio.to_thread(self.user, token)).get('login')
            except (OSError, ValueError, urllib.error.URLError):
                account = None
            await asyncio.to_thread(self.save, token, account)
            self.link = {'state': 'connected', 'message': f'Connected{" as " + account if account else ""}: reports go up after every update'}
            return
