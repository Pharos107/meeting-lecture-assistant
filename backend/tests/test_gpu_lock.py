"""Giữ chỗ và trao khóa GPU khi job nhường cho phiên nghe."""

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET", "t" * 32)

from app.core.config import get_settings
from app.services import gpu_lock


class ReservationContract:
    """Cùng một hợp đồng cho khóa trong tiến trình và khóa Redis."""

    def reset(self) -> None:
        raise NotImplementedError

    def test_hand_over_reserves_for_the_requester_only(self) -> None:
        self.reset()
        lock = gpu_lock.get_gpu_lock()
        self.assertTrue(lock.acquire("job-1"))
        self.assertFalse(gpu_lock.acquire_for("phien-a", "user-a"))
        self.assertFalse(gpu_lock.hand_over("job-khac", "user-a"))
        self.assertTrue(gpu_lock.hand_over("job-1", "user-a"))
        self.assertTrue(gpu_lock.is_reservation(gpu_lock.lock_owner()))
        # Job nhả khóa sau khi trao không xóa chỗ đã giữ.
        lock.release("job-1")
        self.assertFalse(lock.acquire("job-2"))
        self.assertFalse(gpu_lock.acquire_for("phien-b", "user-b"))
        self.assertTrue(gpu_lock.acquire_for("phien-a", "user-a"))
        self.assertEqual(gpu_lock.lock_owner(), "phien-a")
        lock.release("phien-a")
        self.assertTrue(gpu_lock.acquire_for("phien-b", "user-b"))

    def test_wanted_flag_names_the_requester(self) -> None:
        self.reset()
        self.assertIsNone(gpu_lock.gpu_wanted())
        gpu_lock.want_gpu("user-a")
        self.assertEqual(gpu_lock.gpu_wanted(), "user-a")
        gpu_lock.clear_gpu_wanted()
        self.assertIsNone(gpu_lock.gpu_wanted())


class MemoryReservationTests(ReservationContract, unittest.TestCase):
    def setUp(self) -> None:
        os.environ["REDIS_URL"] = ""
        get_settings.cache_clear()

    def reset(self) -> None:
        gpu_lock._memory.owner = None
        gpu_lock._memory.deadline = 0.0
        gpu_lock.clear_gpu_wanted()


@unittest.skipUnless(os.environ.get("TEST_REDIS_URL"), "Đặt TEST_REDIS_URL để thử với Redis thật.")
class RedisReservationTests(ReservationContract, unittest.TestCase):
    def setUp(self) -> None:
        os.environ["REDIS_URL"] = os.environ["TEST_REDIS_URL"]
        get_settings.cache_clear()

    def tearDown(self) -> None:
        self.reset()
        os.environ["REDIS_URL"] = ""
        get_settings.cache_clear()

    def reset(self) -> None:
        gpu_lock.redis_client(os.environ["TEST_REDIS_URL"]).delete("gpu:lock", "gpu:wanted")
