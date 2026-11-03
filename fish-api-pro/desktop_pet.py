"""Windows desktop fish: native transparent window and real model conversations."""
import json
import math
import os
from pathlib import Path
import queue
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from PySide6.QtCore import Qt, QTimer, QPoint, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QPainterPath, QFont
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QFrame, QVBoxLayout, QLabel, QTextEdit, QPushButton, QHBoxLayout, QCheckBox

ROOT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:8765'


class LocalClient:
    def __init__(self):
        self.token = None
        self.session = None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def connect(self):
        try:
            html = self.opener.open(BASE + '/', timeout=3).read().decode('utf-8')
        except (OSError, urllib.error.URLError):
            options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
            # Keep a startup error log instead of silently losing launch failures.
            with (ROOT / 'pet-service.log').open('ab') as log:
                subprocess.Popen([sys.executable, '-X', 'utf8', '-u', str(ROOT / 'server.py'), '--no-browser'], cwd=ROOT, stdout=log, stderr=log, **options)
            end = time.monotonic() + 15
            while True:
                try:
                    html = self.opener.open(BASE + '/', timeout=2).read().decode('utf-8')
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() >= end:
                        raise RuntimeError('本地服务未启动，请查看 pet-service.log，或先运行 start.bat。')
                    time.sleep(.25)
        if 'MODEL TERMINAL' not in html or '大肥鱼' not in html:
            raise RuntimeError('8765 端口被其他程序占用，请先检查。')
        match = re.search(r"X-Local-Token':'([^']+)'", html)
        if not match:
            raise RuntimeError('终端版本不匹配，请使用同一安装包中的程序。')
        self.token = match.group(1)
        state = self.request('state')
        if self.session and not any(s['id'] == self.session for s in state.get('sessions', [])):
            self.session = None
        return state

    def request(self, route, body=None):
        headers = {'X-Local-Token': self.token or '', 'Content-Type': 'application/json'}
        data = None if body is None else json.dumps(body).encode('utf-8')
        req = urllib.request.Request(BASE + '/api/' + route, data=data, headers=headers)
        try:
            with self.opener.open(req, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.load(exc).get('error', '本地接口返回错误')
            except Exception:
                detail = '本地接口 HTTP ' + str(exc.code)
            raise RuntimeError(detail) from None
        except (OSError, urllib.error.URLError):
            raise RuntimeError('连接超时或服务已关闭，请重试。') from None

    def chat(self, text):
        state = self.connect()
        if not any(p.get('hasKey') and p.get('model') for p in state['ports']):
            raise RuntimeError('先右键打开终端，在“模型端口”添加 API、密钥和模型，再来找我聊天。')
        if self.session is None:
            state = self.request('session', {'title': '桌宠对话', 'system': '你是桌面伙伴大肥鱼。用自然、亲切、简洁的中文回答。'})
            self.session = state['sessions'][-1]['id']
        state = self.request('converse', {'id': self.session, 'message': text})
        session = next(s for s in state['sessions'] if s['id'] == self.session)
        return session['messages'][-1]['content']


class Bubble(QFrame):
    def __init__(self, pet):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.pet = pet
        self.setObjectName('bubble')
        self.setStyleSheet('#bubble{background:#f0faff;border:2px solid #60bde9;border-radius:16px} QLabel{color:#15354a;font-size:14px;background:transparent;border:0} QPushButton{background:#d9effa;border:0;border-radius:7px;padding:5px;color:#28556c}')
        layout = QVBoxLayout(self)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.PlainText)
        self.text.setMaximumHeight(170)
        layout.addWidget(self.text)
        close = QPushButton('收起气泡 ×')
        close.clicked.connect(self.hide)
        layout.addWidget(close)
        self.setFixedWidth(300)

    def say(self, text):
        self.text.setText(text[:400] + ('…\n完整回答在聊天窗口。' if len(text) > 400 else ''))
        self.adjustSize()
        self.show()
        self.follow()

    def follow(self):
        screen = self.pet.screen().availableGeometry()
        x = max(screen.left(), min(self.pet.x() - 60, screen.right() - self.width() + 1))
        y = self.pet.y() - self.height() - 6
        if y < screen.top():
            y = self.pet.y() + self.pet.height() + 6
        y = max(screen.top(), min(y, screen.bottom() - self.height() + 1))
        self.move(x, y)


class Chat(QFrame):
    def __init__(self, pet):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.pet = pet
        self.setWindowTitle('大肥鱼 · 桌宠聊天')
        self.resize(420, 470)
        self.setStyleSheet('QFrame{background:#122331;color:#e7f4ff} QTextEdit{background:#203747;color:#e7f4ff;border:1px solid #34566b;border-radius:8px;padding:8px} QPushButton{background:#51bcef;border:0;border-radius:8px;padding:10px;color:#102c3c} QLabel{color:#bbd7e7}')
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('真实调用当前模型，可能计费；会话保存在本机。'))
        self.history = QTextEdit()
        self.history.setReadOnly(True)
        layout.addWidget(self.history)
        self.input = QTextEdit()
        self.input.setPlaceholderText('输入消息，再点击发送（最多 12000 字）')
        self.input.setMaximumHeight(100)
        layout.addWidget(self.input)
        row = QHBoxLayout()
        self.send = QPushButton('发送')
        self.send.clicked.connect(self.submit)
        row.addWidget(self.send)
        self.new = QPushButton('新对话')
        self.new.clicked.connect(self.new_chat)
        row.addWidget(self.new)
        layout.addLayout(row)
        terminal = QPushButton('打开终端 · 配置 API')
        terminal.clicked.connect(pet.open_terminal)
        layout.addWidget(terminal)

    def append(self, role, text):
        cursor = self.history.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(role + '\n' + text + '\n\n')
        self.history.setTextCursor(cursor)
        self.history.ensureCursorVisible()

    def submit(self):
        text = self.input.toPlainText().strip()
        if not text or self.pet.busy:
            return
        if len(text) > 12000:
            self.pet.bubble.say('消息太长了，最多 12000 字。')
            return
        self.input.clear()
        self.append('你', text)
        self.send.setEnabled(False)
        self.new.setEnabled(False)
        self.pet.busy = True
        self.pet.bubble.say('让我想一想…')
        self.pet.work(lambda: self.pet.client.chat(text), self.finished)

    def finished(self, result, error):
        self.pet.busy = False
        self.send.setEnabled(True)
        self.new.setEnabled(True)
        text = error or result
        self.append('提示' if error else '大肥鱼', text)
        self.pet.bubble.say(text)
        if error:
            self.input.setPlaceholderText('发送失败，可重新输入重试。')

    def new_chat(self):
        if self.pet.busy:
            return
        self.pet.client.session = None
        self.history.clear()
        self.pet.bubble.say('新对话准备好啦！')


class Fish(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle('大肥鱼桌宠')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(190, 145)
        self.setCursor(Qt.OpenHandCursor)
        self.client = LocalClient()
        self.results = queue.Queue()
        self.busy = False
        self.quiet = False
        self.tick = 0
        self.drag = None
        self.moved = False
        self.bubble = Bubble(self)
        self.chat = Chat(self)
        area = QApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 30, area.bottom() - self.height() - 20)
        self.load_position()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(50)
        self.greeting = QTimer(self)
        self.greeting.timeout.connect(self.idle)
        self.greeting.start(90000)

    def load_position(self):
        try:
            data = json.loads((ROOT / 'pet-position.json').read_text('utf-8'))
            point = QPoint(int(data['x']), int(data['y']))
            if any(s.availableGeometry().contains(point) for s in QApplication.screens()):
                self.move(point)
                self.clamp()
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def clamp(self):
        area = self.screen().availableGeometry()
        self.move(max(area.left(), min(self.x(), area.right() - self.width() + 1)), max(area.top(), min(self.y(), area.bottom() - self.height() + 1)))

    def save_position(self):
        try:
            (ROOT / 'pet-position.json').write_text(json.dumps({'x': self.x(), 'y': self.y()}), 'utf-8')
        except OSError:
            pass

    def work(self, operation, callback):
        def run():
            try:
                self.results.put((callback, operation(), None))
            except Exception as exc:
                self.results.put((callback, None, str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def animate(self):
        self.tick += 1
        while True:
            try:
                callback, result, error = self.results.get_nowait()
            except queue.Empty:
                break
            callback(result, error)
        self.update()

    def idle(self):
        if not self.quiet and not self.busy and not self.chat.isVisible():
            self.bubble.say(random.choice(['起来活动一下？我陪你游两圈。', '喝口水，休息一下眼睛吧。', '双击我就可以聊天，右键还有更多选项。']))
            QTimer.singleShot(12000, self.hide_idle)

    def hide_idle(self):
        if not self.busy and not self.chat.isVisible():
            self.bubble.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(0, math.sin(self.tick / 9) * 3)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 28))
        p.drawEllipse(QRectF(28, 122, 128, 10))
        tail = QPainterPath()
        tail.moveTo(143, 68)
        tail.quadTo(165, 42 + math.sin(self.tick / 6) * 5, 183, 47)
        tail.quadTo(173, 76, 183, 99)
        tail.quadTo(158, 99, 143, 86)
        tail.closeSubpath()
        p.setBrush(QColor('#258dbf'))
        p.drawPath(tail)
        p.setBrush(QColor('#67d5f5'))
        p.drawEllipse(QRectF(15, 26, 147, 99))
        p.setBrush(QColor('#c8f4f7'))
        p.drawEllipse(QRectF(28, 77, 119, 43))
        p.setBrush(QColor('#38b1dc'))
        p.drawEllipse(QRectF(95, 75, 30, 18))
        blink = self.tick % 100 < 4
        p.setPen(QPen(QColor('#143c53'), 4, Qt.SolidLine, Qt.RoundCap))
        if blink:
            p.drawLine(43, 60, 57, 60)
            p.drawLine(77, 60, 91, 60)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#143c53'))
            p.drawEllipse(QRectF(45, 51, 12, 18))
            p.drawEllipse(QRectF(78, 51, 12, 18))
            p.setBrush(QColor('white'))
            p.drawEllipse(QRectF(48, 53, 4, 5))
            p.drawEllipse(QRectF(81, 53, 4, 5))
        p.setBrush(QColor('#f6a9b3'))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(29, 73, 20, 9))
        p.drawEllipse(QRectF(88, 73, 20, 9))
        p.setPen(QPen(QColor('#22556b'), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(57, 69, 22, 16), 190 * 16, 160 * 16)
        p.setPen(QColor('#d1f5ff'))
        p.setFont(QFont('Microsoft YaHei', 9))
        p.drawText(QRectF(15, 129, 150, 16), Qt.AlignCenter, '思考中…' if self.busy else '大肥鱼 · 双击聊天')
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag = event.globalPosition().toPoint() - self.pos()
            self.press = event.globalPosition().toPoint()
            self.moved = False
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.drag is not None and event.buttons() & Qt.LeftButton:
            if (event.globalPosition().toPoint() - self.press).manhattanLength() > 5:
                self.moved = True
            if self.moved:
                self.move(event.globalPosition().toPoint() - self.drag)
                self.bubble.follow()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.drag is not None:
            self.drag = None
            self.setCursor(Qt.OpenHandCursor)
            self.clamp()
            self.bubble.follow()
            self.save_position()
            if not self.moved and not self.busy:
                self.bubble.say(random.choice(['咕噜咕噜～双击我聊天吧！', '摸摸头，今天也要开心。', '我在呢！右键可以打开终端。']))

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.open_chat()

    def open_chat(self):
        self.chat.show()
        self.chat.raise_()
        self.chat.activateWindow()
        self.chat.input.setFocus()

    def open_terminal(self):
        self.work(self.client.connect, lambda result, error: self.bubble.say(error) if error else webbrowser.open(BASE))

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('和大肥鱼聊天', self.open_chat)
        menu.addAction('打开模型终端', self.open_terminal)
        silent = menu.addAction('安静模式（关闭主动提醒）')
        silent.setCheckable(True)
        silent.setChecked(self.quiet)
        silent.triggered.connect(lambda checked: setattr(self, 'quiet', checked))
        menu.addAction('收起气泡', self.bubble.hide)
        menu.addSeparator()
        menu.addAction('退出桌宠（终端服务保留）', self.quit_pet)
        menu.exec(event.globalPos())

    def quit_pet(self):
        self.save_position()
        self.bubble.close()
        self.chat.close()
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    # A local mutex prevents multiple copies launching duplicate pets.
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    probe = QLocalSocket()
    probe.connectToServer('fish-api-desktop-pet-v1')
    if probe.waitForConnected(200):
        return 0
    lock = QLocalServer()
    QLocalServer.removeServer('fish-api-desktop-pet-v1')
    if not lock.listen('fish-api-desktop-pet-v1'):
        return 1
    pet = Fish()
    pet.show()
    if '--smoke-test' in sys.argv:
        from PySide6.QtTest import QTest
        def smoke():
            try:
                assert pet.isVisible()
                assert not pet.grab().isNull()
                QTest.mouseClick(pet, Qt.LeftButton, pos=QPoint(70, 60))
                assert pet.bubble.isVisible()
                pet.open_chat()
                assert pet.chat.isVisible()
                pet.chat.append('模型', '<script>literal text</script>')
                assert '<script>' in pet.chat.history.toPlainText()
                pet.chat.input.setPlainText('Windows desktop smoke test')
                pet.client.chat = lambda text: '测试回答：' + text
                pet.chat.submit()
                def done():
                    try:
                        assert not pet.busy
                        assert '测试回答' in pet.chat.history.toPlainText()
                        pet.quit_pet()
                    except Exception:
                        import traceback
                        traceback.print_exc()
                        app.exit(1)
                QTimer.singleShot(800, done)
            except Exception:
                import traceback
                traceback.print_exc()
                app.exit(1)
        QTimer.singleShot(400, smoke)
    else:
        QTimer.singleShot(500, lambda: pet.bubble.say('你好，我是大肥鱼！拖动我挪位置，双击聊天，右键打开菜单。'))
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
