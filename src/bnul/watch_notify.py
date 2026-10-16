"""Small, durable Slack outbox; no library credentials in messages or HTTP errors."""
import json
import os
import re
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

from .client import Error, NoRedirect


from .env import env_value as setting


def safe_error(exc):
    # Server responses are not trusted to omit credentials. Also strip common bearer strings.
    text = str(exc)
    for key in ('BNUL_USERNAME', 'BNUL_PASSWORD', 'BNUL_TOKEN', 'SLACK_BOT_TOKEN'):
        try:
            value = setting(key)
        except Error:
            value = None
        if value:
            text = text.replace(value, '[redacted]')
    text = re.sub(r'xox[baprs]-[A-Za-z0-9-]+|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[redacted]', text)
    return text[:800]


def send_slack(text):
    token = setting('SLACK_BOT_TOKEN')
    channel = setting('BNUL_SLACK_CHANNEL') or setting('SLACK_HOME_CHANNEL')
    thread = setting('BNUL_SLACK_THREAD') or setting('SLACK_HOME_CHANNEL_THREAD_ID')
    if not token or not channel:
        raise Error('Slack 通知缺少 SLACK_BOT_TOKEN 或目标会话', 'NOTIFY_CONFIG_INVALID')
    payload = {'channel': channel, 'text': text[:3500], 'mrkdwn': False,
               'parse': 'none', 'unfurl_links': False, 'unfurl_media': False}
    if thread:
        payload['thread_ts'] = thread
    request = Request('https://slack.com/api/chat.postMessage', json.dumps(payload).encode(),
                      {'Content-Type': 'application/json; charset=utf-8',
                       'Authorization': 'Bearer ' + token}, method='POST')
    try:
        with build_opener(NoRedirect(), ProxyHandler({})).open(request, timeout=15) as response:
            result = json.load(response)
    except HTTPError as exc:
        retry = exc.headers.get('Retry-After', '120') if exc.headers else '120'
        raise Error('Slack HTTP ' + str(exc.code), 'NOTIFY_FAILED',
                    {'retryAfter': min(3600, max(120, int(retry))) if retry.isdigit() else 120}) from None
    except (URLError, OSError, ValueError, Error):
        raise Error('Slack 通知请求失败，将保留并重试', 'NOTIFY_FAILED') from None
    if not isinstance(result, dict) or result.get('ok') is not True or not result.get('ts'):
        code = result.get('error', 'invalid_response') if isinstance(result, dict) else 'invalid_response'
        # Do not echo arbitrary response text, which might contain submitted data.
        code = code if isinstance(code, str) and re.fullmatch(r'[a-z_]+', code) else 'invalid_response'
        raise Error('Slack 拒绝通知：' + code, 'NOTIFY_FAILED')
    return {'channel': result.get('channel'), 'ts': result['ts']}


def enqueue(store, key, message, now):
    notices = store.data.setdefault('notifications', {})
    if key in notices:
        return
    notices[key] = {'id': str(uuid.uuid4()), 'text': message, 'createdAt': now.isoformat(),
                    'attempts': 0, 'nextAttempt': 0}
    store.save()


def flush(store, now, sender=send_slack, allowed=None):
    errors = []
    due = [(key, item) for key, item in store.data.get('notifications', {}).items()
           if not item.get('deliveredAt') and item.get('nextAttempt', 0) <= now.timestamp()]
    for key, item in due[:3]:
        if allowed is not None and not allowed():
            break
        try:
            receipt = sender(item['text'])
        except (Error, OSError) as exc:
            item['attempts'] += 1
            delay = min(3600, 120 * 2 ** min(item['attempts'] - 1, 5))
            if isinstance(exc, Error) and isinstance(exc.data, dict):
                delay = max(delay, exc.data.get('retryAfter', 0))
            item.update(lastError=safe_error(exc), nextAttempt=now.timestamp() + delay)
            errors.append(item['lastError'])
        else:
            item.update(deliveredAt=now.isoformat(), receipt=receipt)
            item.pop('lastError', None)
        store.save()
    return errors
