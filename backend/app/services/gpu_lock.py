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


# Phiên nghe gặp khóa của job PT1 thì đặt cờ này. Job đọc cờ giữa hai chunk, nhả khóa,
# rồi chạy tiếp sau. Cờ tự hết hạn để job không chờ mãi khi người dùng bỏ ý định ghi.
_WANTED_KEY = "gpu:wanted"
WANTED_TTL_S = 30
_wanted_until = 0.0
_wanted_guard = threading.Lock()


def want_gpu() -> None:
    global _wanted_until
    url = get_settings().redis_url
    if url:
        redis_client(url).set(_WANTED_KEY, "1", ex=WANTED_TTL_S)
        return
    with _wanted_guard:
        _wanted_until = time.monotonic() + WANTED_TTL_S


def gpu_wanted() -> bool:
    url = get_settings().redis_url
    if url:
        return bool(redis_client(url).exists(_WANTED_KEY))
    with _wanted_guard:
        return _wanted_until > time.monotonic()


def clear_gpu_wanted() -> None:
    global _wanted_until
    url = get_settings().redis_url
    if url:
        redis_client(url).delete(_WANTED_KEY)
        return
    with _wanted_guard:
        _wanted_until = 0.0


def lock_owner() -> str | None:
    """Id đang giữ gpu:lock, hoặc None khi khóa trống."""
    url = get_settings().redis_url
    if url:
        value = redis_client(url).get(_KEY)
        return value.decode() if isinstance(value, bytes) else value
    with _memory._guard:
        if _memory.owner is not None and _memory.deadline > time.monotonic():
            return _memory.owner
        return None


class LockKeeper:
    """Gia hạn khóa mỗi 10 giây. Phiên nghe chưa có worker thì nhả khóa khi mất nhịp quá 30 giây."""

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
            from app.services.live_heartbeat import age, worker_alive

            started = time.monotonic()
            while not stop.wait(10):
                if until_quiet:
                    # Worker của phiên đã giữ khóa và tự nhả sau pass 2, kể cả khi mất nhịp.
                    if worker_alive(owner):
                        break
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
