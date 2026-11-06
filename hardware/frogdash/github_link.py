"""Connect the dash to GitHub with a short code, so reports and drives upload automatically
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
import tempfile
import time
from uuid import uuid4
import urllib.error
import urllib.parse
import urllib.request

CLIENT_ID = 'Ov23li7DGiineMBNPBYy'   # The owner's Frogdash OAuth app (device flow on); public, not a secret
REPO = 'averyizatt/frogdash'
SCOPE = 'public_repo'
CODE_URL = 'https://github.com/login/device/code'
TOKEN_URL = 'https://github.com/login/oauth/access_token'
USER_URL = 'https://api.github.com/user'


class RefreshRefused(Exception):
    """The saved refresh token can no longer renew this login."""


def token_fields(answer, now):
    fields = {'token': answer['access_token']}
    if answer.get('refresh_token'):
        fields['refresh_token'] = answer['refresh_token']
    for source, target in (('expires_in', 'expires_at'), ('refresh_token_expires_in', 'refresh_expires_at')):
        if isinstance(answer.get(source), (int, float)) and answer[source] > 0:
            fields[target] = now + answer[source]
    return fields


def write_login(path, config, expected_token=None):
    """Replace credentials privately, preserving the dash user's ownership when root renews."""
    path = Path(path)
    previous = path.stat() if path.exists() else None
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        json.dump(config, stream)
    try:
        os.chmod(tmp, 0o600)
        if previous and hasattr(os, 'chown'):
            os.chown(tmp, previous.st_uid, previous.st_gid)
        if expected_token is not None:
            try:
                current = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                current = {}
            if current.get('token') != expected_token:
                raise RuntimeError('GitHub connection changed during renewal; retry the upload')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def post_form(url, fields, timeout=15):
    request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method='POST',
                                     headers={'Accept': 'application/json', 'User-Agent': 'fox-body-dash'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def refresh_login(path, config, force=False, post=post_form, wall=time.time):
    if not config.get('refresh_token'):
        return config
    now = wall()
    if not force and config.get('expires_at', 0) > now + 300:
        return config
    try:
        answer = post(TOKEN_URL, {'client_id': config.get('client_id') or CLIENT_ID,
                                 'grant_type': 'refresh_token', 'refresh_token': config['refresh_token']})
    except urllib.error.HTTPError as error:
        try:
            answer = json.loads(error.read())
        except ValueError:
            answer = {}
    if answer.get('error') in ('bad_refresh_token', 'invalid_grant', 'expired_token'):
        raise RefreshRefused('GitHub login needs to be connected again')
    if not answer.get('access_token') or not answer.get('refresh_token'):
        raise RuntimeError('GitHub could not renew this login; the reports will retry later')
    updated = {k: v for k, v in config.items() if k not in ('token', 'refresh_token', 'expires_at', 'refresh_expires_at')}
    updated.update(token_fields(answer, now))
    write_login(path, updated, expected_token=config['token'])
    return updated


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
        status = self.read('upload-status.json')
        status = status if isinstance(status, dict) else {}
        last = {k: v for k, v in status.items() if k in ('time', 'state', 'message')}
        # Reports kept on the Pi, as the uploader counted them: their folder is root's alone
        # (the dash reading it was the 500 on the car, October 2026).
        held = status.get('held') if isinstance(status.get('held'), int) else 0
        try:
            asked = (self.folder / 'update-request').read_text(encoding='utf-8').strip() == 'upload'
        except OSError:
            asked = False
        link = dict(self.link)
        if link.get('state') == 'waiting' and self.wall() > link.get('expires_at', 0):
            link = self.link = {'state': 'failed', 'message': 'The code ran out before it was entered. Press Connect GitHub for a new one'}
        login = status.get('login') if isinstance(status.get('login'), dict) else {}
        matching = login.get('login_id') == config.get('login_id')
        expires = (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(config['expires_at']))
                   if config.get('expires_at') else login.get('expires') if matching else None)
        return {'configured': bool(config.get('token')), 'repo': config.get('repo') or None, 'account': config.get('account'),
                'via': 'device code' if config.get('via') == 'device code' else ('token' if config.get('token') else None),
                'expires': expires if config.get('token') else None,
                'renewable': bool(config.get('refresh_token')),
                'ready': bool(self.client_id), 'last': last or None, 'held': held, 'link': link,
                'sending': asked or status.get('state') == 'sending'}

    def send_now(self):
        """Ask the updater (root, frogdash-update.path) to send saved reports, a fresh report,
        and all unsent drive recordings. An error text, or None when asked."""
        if not (self.read('log-upload.json') or {}).get('token'):
            return 'Connect GitHub first'
        request = self.folder / 'update-request'
        try:
            waiting = request.read_text(encoding='utf-8').strip()
        except OSError:
            waiting = ''
        if waiting and waiting != 'upload':
            return 'An update is about to run: it sends the reports too'
        request.write_text('upload', encoding='utf-8')
        return None

    def save(self, token, account, answer=None):
        self.folder.mkdir(parents=True, exist_ok=True)
        config = {'repo': REPO, 'account': account, 'via': 'device code',
                  'client_id': self.client_id, 'login_id': uuid4().hex,
                  **token_fields(answer or {'access_token': token}, self.wall())}
        write_login(self.config_path, config)

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
            await asyncio.to_thread(self.save, token, account, answer)
            # The reports kept on the Pi go now, not at the next update (October 2026: two
            # waited after connecting, because nothing sent them until an update).
            sent = await asyncio.to_thread(self.send_now) is None
            self.link = {'state': 'connected', 'message': f'Connected{" as " + account if account else ""}: '
                         + ('sending reports and drives now; after that they upload automatically' if sent else 'reports and drives upload automatically')}
            return
