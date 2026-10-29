"""Khóa Redis gpu:lock. Không có REDIS_URL thì dùng khóa trong tiến trình cho test."""

import threading
import time

from app.core.config import get_settings

_KEY = "gpu:lock"
_redis_clients: dict[str, object] = {}
_redis_guard = threading.Lock()


def redis_client(url: str):
    import redis

    with _redis_guard:
        client = _redis_clients.get(url)
        if client is None:
            client = redis.Redis.from_url(url)
            _redis_clients[url] = client
        return client


class MemoryGpuLock:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self.owner: str | None = None
        self.deadline = 0.0

    def acquire(self, owner: str, ttl: int = 30) -> bool:
        now = time.monotonic()
        with self._guard:
            if self.owner is not None and self.owner != owner and self.deadline > now:
                return False
            self.owner = owner
            self.deadline = now + ttl
            return True

    def refresh(self, owner: str, ttl: int = 30) -> bool:
        now = time.monotonic()
        with self._guard:
            if self.owner != owner:
                return False
            self.deadline = now + ttl
            return True

    def release(self, owner: str) -> None:
        with self._guard:
            if self.owner == owner:
                self.owner = None
                self.deadline = 0.0


class RedisGpuLock:
    def __init__(self, url: str) -> None:
        self.url = url

    def _client(self):
        return redis_client(self.url)

    def acquire(self, owner: str, ttl: int = 30) -> bool:
        return bool(self._client().set(_KEY, owner, nx=True, ex=ttl))

    def refresh(self, owner: str, ttl: int = 30) -> bool:
        script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
        )
        return bool(self._client().eval(script, 1, _KEY, owner, str(ttl)))

    def release(self, owner: str) -> None:
        script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('del', KEYS[1]) else return 0 end"
        )
        self._client().eval(script, 1, _KEY, owner)


_memory = MemoryGpuLock()


def get_gpu_lock() -> MemoryGpuLock | RedisGpuLock:
    url = get_settings().redis_url
    if url:
        return RedisGpuLock(url)
    return _memory


class LockKeeper:
    """Gia hạn khóa mỗi 10 giây. Phiên nghe nhả khóa khi mất nhịp quá 30 giây."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._stops: dict[str, threading.Event] = {}

    def start(self, owner: str, *, until_quiet: bool = False) -> None:
        with self._guard:
            if owner in self._stops:
                return
            stop = threading.Event()
            self._stops[owner] = stop

        def run() -> None:
            from app.services.live_heartbeat import age

            started = time.monotonic()
            while not stop.wait(10):
                if until_quiet:
                    quiet = age(owner)
                    if quiet is None and time.monotonic() - started >= 60:
                        get_gpu_lock().release(owner)
                        break
                    if quiet is not None and quiet > 30:
                        get_gpu_lock().release(owner)
                        break
                if not get_gpu_lock().refresh(owner):
                    break
            with self._guard:
                current = self._stops.get(owner)
                if current is stop:
                    self._stops.pop(owner, None)

        threading.Thread(target=run, name=f"gpu-refresh-{owner[:8]}", daemon=True).start()

    def stop(self, owner: str) -> None:
        with self._guard:
            stop = self._stops.pop(owner, None)
        if stop is not None:
            stop.set()

    def stop_all(self) -> None:
        with self._guard:
            stops = list(self._stops.values())
            self._stops.clear()
        for stop in stops:
            stop.set()


keeper = LockKeeper()
