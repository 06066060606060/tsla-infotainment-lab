"""Keep one control panel per user and bring it back on a second launch."""
import hashlib
import json
from pathlib import Path
import time

from PySide6.QtCore import QObject, QLockFile, QStandardPaths
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class DesktopInstance(QObject):
    def __init__(self, parent=None, directory=None):
        super().__init__(parent)
        directory = Path(directory or QStandardPaths.writableLocation(QStandardPaths.GenericCacheLocation)) / 'tsla-infotainment-lab'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        digest = hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:20]
        self.name = 'infotainment-lab-' + digest
        self.lock = QLockFile(str(directory / 'desktop.lock'))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)

    def acquire(self, request):
        if self.lock.tryLock(0):
            # Only the lock owner can remove a socket left behind by a crash.
            QLocalServer.removeServer(self.name)
            if not self.server.listen(self.name):
                self.lock.unlock()
                raise RuntimeError('Cannot create the local desktop connection: ' + self.server.errorString())
            return True
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(250):
                socket.write(json.dumps(request).encode() + b'\n')
                socket.waitForBytesWritten(1000)
                if socket.waitForReadyRead(2000) and bytes(socket.readAll()) == b'opened':
                    return False
                break
            time.sleep(.05)
        raise RuntimeError('The existing Infotainment Lab window did not respond. Close that control panel, then open the app again.')

    def attach(self, callback):
        def accept():
            while self.server.hasPendingConnections():
                socket = self.server.nextPendingConnection()
                socket.disconnected.connect(socket.deleteLater)

                def receive(peer=socket):
                    if peer.bytesAvailable() > 65536:
                        peer.abort()
                        return
                    if not peer.canReadLine():
                        return
                    try:
                        request = json.loads(bytes(peer.readLine()))
                        files = request.get('files', [])
                        if not isinstance(files, list) or not all(isinstance(path, str) for path in files):
                            raise ValueError('Invalid file list')
                        callback(files)
                        peer.write(b'opened')
                        peer.flush()
                    except (ValueError, TypeError, AttributeError):
                        pass
                    peer.disconnectFromServer()

                socket.readyRead.connect(receive)
                receive()
        self.server.newConnection.connect(accept)
