import json, os, secrets, threading, uuid, webbrowser
import io, wave
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlparse, unquote
from urllib.error import HTTPError

ROOT = Path(__file__).parent
DATA = ROOT / 'settings.json'
TOKEN = secrets.token_urlsafe(32)
KEYS = {}
STATE = json.loads(DATA.read_text('utf-8')) if DATA.exists() else {'ports': [], 'config': {'pet': False, 'qqVoice': False, 'petVoice': False}}
STATE.setdefault('activePort', STATE['ports'][0]['id'] if STATE['ports'] else None)
STATE.setdefault('autoSwitch', True)
STATE.setdefault('lastRoute', [])
for index, port in enumerate(STATE['ports']):
    port.setdefault('priority', index + 1)

def ordered_ports():
    return sorted(STATE['ports'], key=lambda p: p.get('priority', 100))

def read_logs():
    path = DATA.parent / 'logs' / 'runtime.json'
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text('utf-8'))
    except (ValueError, OSError):
        return [{'time': '', 'level': 'ERROR', 'event': '日志读取失败', 'detail': '请检查 logs/runtime.json 文件'}]

def log_event(level, event, detail=''):
    try:
        folder = DATA.parent / 'logs'
        folder.mkdir(exist_ok=True)
        entries = read_logs()[-999:]
        entries.append({'time': datetime.now().astimezone().isoformat(timespec='seconds'), 'level': level, 'event': event, 'detail': detail})
        temp = folder / 'runtime.tmp'
        temp.write_text(json.dumps(entries, ensure_ascii=False), 'utf-8')
        temp.replace(folder / 'runtime.json')
    except OSError:
        print('日志写入失败，请检查 logs 目录权限')

def routed_chat(message):
    if not isinstance(message, str) or not message.strip():
        raise ValueError('请输入消息')
    ports = ordered_ports()
    active = next((p for p in ports if p['id'] == STATE['activePort']), None)
    candidates = ([active] if active else []) + [p for p in ports if p is not active]
    if not STATE['autoSwitch']:
        candidates = [active] if active else []
    STATE['lastRoute'] = []
    for p in candidates:
        reason = None
        if not KEYS.get(p['id']) or not p.get('model'):
            reason = '缺少密钥或模型名称'
        if reason:
            STATE['lastRoute'].append({'name': p['name'], 'result': reason})
            continue
        try:
            r = remote(p, '/chat/completions', {'model': p['model'], 'messages': [{'role': 'user', 'content': message}], 'stream': False})
            reply = r['choices'][0]['message']['content']
            if not isinstance(reply, str) or not reply.strip():
                raise ValueError('模型未返回有效文本')
            usage = r.get('usage') or {}
            tokens = max(0, int(usage.get('total_tokens', 0)))
        except (ValueError, KeyError, IndexError, TypeError):
            p['status'] = '调用失败'
            STATE['lastRoute'].append({'name': p['name'], 'result': '调用失败（额度、网络、接口错误或无效响应），尝试下一端口'})
            continue
        p['tokens'] = p.get('tokens', 0) + tokens
        p['status'] = '接口可达'
        p.pop('error', None)
        STATE['activePort'] = p['id']
        STATE['lastRoute'].append({'name': p['name'], 'result': '调用成功，已作为当前端口'})
        save()
        return {'reply': reply, 'usage': usage, 'portName': p['name']}
    save()
    raise ValueError('所有候选端口均不可用，请检查首页切换记录、密钥、模型与额度')

def save():
    temp = DATA.with_suffix('.tmp')
    temp.write_text(json.dumps(STATE, ensure_ascii=False, indent=2), 'utf-8')
    temp.replace(DATA)

def public():
    return {**STATE, 'ports': [{**p, 'hasKey': bool(KEYS.get(p['id']))} for p in STATE['ports']]}

def store_voice(target, raw, name):
    if target not in ('qq', 'pet'):
        raise ValueError('未知语音目标')
    try:
        with wave.open(io.BytesIO(raw), 'rb') as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or rate != 16000:
                raise ValueError('请通过界面上传音频，存储格式须为 16kHz 单声道 PCM')
            duration = frames / rate
            if not 0 < duration <= 900:
                raise ValueError('音频时长须在 0 至 15 分钟以内')
            if len(audio.readframes(frames)) != frames * 2:
                raise ValueError('音频文件不完整')
    except (wave.Error, EOFError):
        raise ValueError('无法读取音频文件') from None
    folder = DATA.parent / 'voices'
    folder.mkdir(exist_ok=True)
    filename = target + '-' + uuid.uuid4().hex + '.wav'
    path = folder / filename
    path.write_bytes(raw)
    voices = STATE.setdefault('voices', {})
    old = voices.get(target)
    voices[target] = {'name': name[:160], 'duration': round(duration, 2), 'file': filename}
    try:
        save()
    except Exception:
        if old is None:
            voices.pop(target, None)
        else:
            voices[target] = old
        path.unlink(missing_ok=True)
        raise
    if old and Path(old['file']).name == old['file']:
        (folder / old['file']).unlink(missing_ok=True)
    log_event('INFO', '参考音频保存', ('QQ' if target == 'qq' else '桌宠') + '：' + str(round(duration, 2)) + ' 秒')
    return public()

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def remote(p, path, body=None):
    key = KEYS.get(p['id'])
    if not key:
        raise ValueError('请先编辑端口并填写密钥（重启后需要重新填写）')
    req = Request(p['url'].rstrip('/') + path, data=None if body is None else json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with build_opener(NoRedirect).open(req, timeout=20) as r:
            return json.load(r)
    except HTTPError as e:
        raise ValueError('上游 HTTP ' + str(e.code) + '，请检查地址、密钥、权限或额度') from None
    except Exception:
        raise ValueError('上游连接失败或响应格式无效，请检查网络与 API 地址') from None

def action(route, b):
    if route == '/api/send':
        return routed_chat(b.get('message'))
    if route == '/api/routing':
        if 'activePort' in b:
            if not any(p['id'] == b['activePort'] for p in STATE['ports']):
                raise ValueError('端口不存在')
            STATE['activePort'] = b['activePort']
        if 'autoSwitch' in b:
            STATE['autoSwitch'] = bool(b['autoSwitch'])
        if 'priority' in b:
            priority = int(b['priority'])
            p = next((p for p in STATE['ports'] if p['id'] == b.get('id')), None)
            if not p or not 1 <= priority <= 999:
                raise ValueError('优先级必须为 1 至 999')
            p['priority'] = priority
        save()
    elif route == '/api/port':
        url = str(b.get('url', '')).strip().rstrip('/')
        u = urlparse(url)
        if u.scheme not in ('https', 'http') or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError('请输入有效 API 基础地址，不含密钥、查询参数或片段')
        if u.scheme == 'http' and u.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('远程 API 必须使用 HTTPS')
        if b.get('protocol') not in ('deepseek', 'openai'):
            raise ValueError('暂不支持该协议')
        if not str(b.get('name', '')).strip():
            raise ValueError('请输入名称')
        p = next((p for p in STATE['ports'] if p['id'] == b.get('id')), None)
        if p is None:
            p = {'id': uuid.uuid4().hex, 'tokens': 0, 'priority': len(STATE['ports']) + 1}
            STATE['ports'].append(p)
            if not STATE['activePort']:
                STATE['activePort'] = p['id']
        if p.get('url') != url:
            KEYS.pop(p['id'], None)
        p.update({k: str(b.get(k, '')).strip() for k in ('name', 'protocol', 'model')})
        p.update(url=url, status='未检测', balance=None)
        if b.get('key'):
            KEYS[p['id']] = str(b['key']).strip()
        save()
    elif route == '/api/delete':
        ids = set(b.get('ids', []))
        STATE['ports'] = [p for p in STATE['ports'] if p['id'] not in ids]
        for i in ids:
            KEYS.pop(i, None)
        if STATE['activePort'] in ids:
            STATE['activePort'] = ordered_ports()[0]['id'] if STATE['ports'] else None
        save()
    elif route == '/api/config':
        STATE['config'] = {k: bool(b.get(k)) for k in ('pet', 'qqVoice', 'petVoice')}
        save()
    elif route in ('/api/check', '/api/chat'):
        p = next((p for p in STATE['ports'] if p['id'] == b.get('id')), None)
        if not p:
            raise ValueError('端口不存在')
        if route == '/api/check':
            p['balance'] = None
            p.pop('balanceError', None)
            p.pop('error', None)
            try:
                remote(p, '/models')
                p['status'] = '接口可达'
                if p['protocol'] == 'deepseek':
                    try:
                        result = remote(p, '/user/balance')
                        p['balance'] = result.get('balance_infos', [])
                        if result.get('is_available') is False:
                            p['status'] = '账户不可用'
                    except ValueError as e:
                        p['balanceError'] = str(e)
            except ValueError as e:
                p['status'] = '检测失败'
                p['error'] = str(e)
            save()
        else:
            if not p['model'] or not str(b.get('message', '')).strip():
                raise ValueError('请填写模型名称与测试消息')
            r = remote(p, '/chat/completions', {'model': p['model'], 'messages': [{'role': 'user', 'content': str(b['message'])}], 'stream': False})
            p['tokens'] += int(r.get('usage', {}).get('total_tokens', 0))
            save()
            return {'reply': r['choices'][0]['message']['content'], 'usage': r.get('usage', {})}
    else:
        raise ValueError('未知操作')
    return public()

business_action = action

def action(route, b):
    labels = {'/api/send': '自动路由对话', '/api/chat': '指定端口对话', '/api/check': '端口检测', '/api/port': '端口保存', '/api/delete': '端口删除', '/api/config': '模型配置保存', '/api/routing': '端口切换或优先级保存'}
    label = labels.get(route, '请求处理')
    log_event('INFO', label, '开始处理')
    try:
        result = business_action(route, b)
    except Exception as e:
        log_event('ERROR', label, '操作失败（' + type(e).__name__ + '），请检查界面提示')
        raise
    finally:
        if route == '/api/send':
            for index, step in enumerate(STATE.get('lastRoute', []), 1):
                success = step['result'].startswith('调用成功')
                log_event('INFO' if success else 'WARN', '路由尝试 ' + str(index), step['result'])
    if route == '/api/check':
        p = next((p for p in STATE['ports'] if p['id'] == b.get('id')), {})
        status = p.get('status', '未知')
        log_event('INFO' if status == '接口可达' else 'WARN', label, status)
    else:
        log_event('INFO', label, '操作成功')
    return result

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def respond(self, code, body, kind='application/json; charset=utf-8'):
        raw = body if isinstance(body, bytes) else body.encode('utf-8') if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)
    def allowed(self):
        return self.headers.get('Host') == '127.0.0.1:8765'
    def do_GET(self):
        if not self.allowed():
            return self.respond(403, {'error': '禁止访问'})
        if urlparse(self.path).path == '/logo.svg':
            return self.respond(200, (ROOT / 'logo.svg').read_bytes(), 'image/svg+xml')
        if urlparse(self.path).path in ('/assets/logo.jpg', '/logo.jpg'):
            return self.respond(200, (ROOT / 'assets' / 'logo.jpg').read_bytes(), 'image/jpeg')
        if self.path == '/':
            return self.respond(200, (ROOT / 'index.html').read_text('utf-8').replace('__TOKEN__', TOKEN), 'text/html; charset=utf-8')
        if self.path == '/api/state' and self.headers.get('X-Local-Token') == TOKEN:
            return self.respond(200, public())
        if self.path == '/api/logs' and self.headers.get('X-Local-Token') == TOKEN:
            return self.respond(200, {'entries': list(reversed(read_logs()))})
        if self.path in ('/api/voice/qq', '/api/voice/pet') and self.headers.get('X-Local-Token') == TOKEN:
            voice = STATE.get('voices', {}).get(self.path.rsplit('/', 1)[1])
            if voice and Path(voice['file']).name == voice['file']:
                path = DATA.parent / 'voices' / voice['file']
                if path.exists():
                    return self.respond(200, path.read_bytes(), 'audio/wav')
        self.respond(404, {'error': '不存在'})
    def do_POST(self):
        if not self.allowed() or self.headers.get('X-Local-Token') != TOKEN:
            return self.respond(403, {'error': '禁止访问'})
        if self.path == '/api/shutdown':
            log_event('INFO', '关闭程序', '收到本机关闭请求')
            self.respond(200, {'ok': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if self.path in ('/api/voice/qq', '/api/voice/pet'):
                if not 44 < n <= 30 * 1024 * 1024:
                    raise ValueError('转换后的音频不得超过 30MB')
                raw = self.rfile.read(n)
                if len(raw) != n:
                    raise ValueError('上传未完成')
                return self.respond(200, store_voice(self.path.rsplit('/', 1)[1], raw, unquote(self.headers.get('X-Audio-Name', '参考音频'))))
            if not 0 < n <= 65536:
                raise ValueError('请求大小不合法')
            b = json.loads(self.rfile.read(n))
            self.respond(200, action(self.path, b))
        except (ValueError, TypeError, KeyError, IndexError) as e:
            log_event('WARN', '请求校验或处理失败', type(e).__name__)
            self.respond(400, {'error': str(e) if isinstance(e, ValueError) else '数据格式不符合接口要求'})
        except Exception:
            log_event('ERROR', '服务处理异常', '请检查本地文件权限或上游响应')
            self.respond(500, {'error': '本地处理失败，请检查文件写入权限或上游响应'})


# Pro extensions: validated portable configuration and persistent conversations.
legacy_action = action

def action(route, b):
    if not isinstance(b, dict):
        raise ValueError('请求必须是 JSON 对象')
    if route == '/api/export':
        return {'version': 1, 'ports': [{k: p.get(k) for k in ('name','url','protocol','model','priority')} for p in STATE['ports']], 'autoSwitch': STATE['autoSwitch']}
    if route == '/api/import':
        rows = b.get('ports')
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError('请提供不超过 100 个端口的配置')
        validated = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('端口格式错误')
            u = urlparse(str(row.get('url', '')))
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError('基础地址不合法')
            if u.scheme == 'http' and u.hostname not in ('localhost','127.0.0.1','::1'):
                raise ValueError('远程 API 必须使用 HTTPS')
            if row.get('protocol') not in ('openai','deepseek') or not str(row.get('name','')).strip():
                raise ValueError('名称或协议不合法')
            priority = int(row.get('priority') or 100)
            if not 1 <= priority <= 999:
                raise ValueError('优先级须为 1 至 999')
            validated.append(dict(id=uuid.uuid4().hex, name=str(row['name'])[:160], url=u.geturl().rstrip('/'), protocol=row['protocol'], model=str(row.get('model') or '')[:200], priority=priority, tokens=0, status='未检测', balance=None))
        STATE['ports'].extend(validated)
        if not STATE['activePort'] and validated:
            STATE['activePort'] = validated[0]['id']
        save()
        log_event('INFO', '配置导入', str(len(validated)) + ' 个端口（追加）')
        return public()
    if route == '/api/models':
        p = next((p for p in STATE['ports'] if p['id'] == b.get('id')), None)
        if not p:
            raise ValueError('端口不存在')
        data = remote(p, '/models')
        return {'models': sorted({str(m['id']) for m in data.get('data', []) if isinstance(m, dict) and m.get('id')})}
    if route == '/api/session':
        sessions = STATE.setdefault('sessions', [])
        if b.get('delete'):
            STATE['sessions'] = [s for s in sessions if s['id'] != b.get('id')]
        else:
            if len(sessions) >= 100:
                raise ValueError('最多保存 100 个会话，请先删除旧会话')
            sessions.append({'id': uuid.uuid4().hex, 'title': str(b.get('title') or '新会话')[:80], 'messages': [], 'system': str(b.get('system') or '')[:4000]})
        save()
        return public()
    if route == '/api/converse':
        import time
        session = next((s for s in STATE.get('sessions',[]) if s['id'] == b.get('id')), None)
        message = b.get('message')
        if not session or not isinstance(message,str) or not message.strip() or len(message)>12000:
            raise ValueError('请选择会话并输入不超过 12000 字的消息')
        if len(session['messages']) >= 100:
            raise ValueError('该会话已达 50 轮，请创建新会话')
        messages = ([{'role':'system','content':session['system']}] if session['system'] else []) + [{'role':m['role'],'content':m['content']} for m in session['messages'][-40:]] + [{'role':'user','content':message}]
        ports = ordered_ports()
        current = next((p for p in ports if p['id']==STATE['activePort']), None)
        candidates = ([current] if current else []) + ([p for p in ports if p is not current] if STATE['autoSwitch'] else [])
        STATE['lastRoute'] = []
        for port in candidates:
            if not KEYS.get(port['id']) or not port.get('model'):
                STATE['lastRoute'].append({'name':port['name'],'result':'缺少密钥或模型'})
                continue
            start = time.monotonic()
            try:
                result = remote(port,'/chat/completions',{'model':port['model'],'messages':messages,'stream':False})
                reply = result['choices'][0]['message']['content']
                if not isinstance(reply,str) or not reply.strip():
                    raise ValueError('模型返回空文本')
                tokens = max(0,int((result.get('usage') or {}).get('total_tokens',0)))
            except (ValueError,KeyError,IndexError,TypeError):
                port['failures'] = port.get('failures',0)+1
                STATE['lastRoute'].append({'name':port['name'],'result':'调用失败，尝试下一端口'})
                continue
            port['tokens'] = port.get('tokens',0)+tokens
            port['requests'] = port.get('requests',0)+1
            port['latencyMs'] = round((time.monotonic()-start)*1000)
            port['status'] = '接口可达'
            STATE['activePort'] = port['id']
            STATE['lastRoute'].append({'name':port['name'],'result':'调用成功'})
            session['messages'].extend([{'role':'user','content':message},{'role':'assistant','content':reply,'port':port['name'],'tokens':tokens}])
            if len(session['messages'])==2:
                session['title'] = message[:30]
            save()
            log_event('INFO','多轮会话','调用成功；耗时 '+str(port['latencyMs'])+'ms')
            return public()
        save()
        log_event('WARN','多轮会话','候选端口全部失败')
        raise ValueError('所有候选端口均不可用，请检查密钥、模型、网络和额度')
    return legacy_action(route,b)

if __name__ == '__main__':
    import socket
    class LocalServer(HTTPServer):
        allow_reuse_address = False
        def server_bind(self):
            if os.name == 'nt':
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()
    try:
        server = LocalServer(('127.0.0.1', 8765), Handler)
    except OSError:
        print('启动失败：8765 端口可能已被旧版本占用。请关闭旧程序终端，再重新启动此文件夹中的 start.bat。')
        raise SystemExit(1)
    print('大肥鱼 API 模型终端：http://127.0.0.1:8765 （Ctrl+C 退出）')
    if '--no-browser' not in __import__('sys').argv:
        webbrowser.open('http://127.0.0.1:8765')
    log_event('INFO', '终端启动', '本地服务已启动')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log_event('INFO', '终端停止', '本地服务已停止')
        server.server_close()
