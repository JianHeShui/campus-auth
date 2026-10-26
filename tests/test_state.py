"""认证状态与退避策略测试：在线复核间隔与失败退避分离（v0.3.2 A 方案）。"""
import unittest

from campus_auth.state import AuthState, RetryPolicy


class RetryPolicyTests(unittest.TestCase):
    def test_default_keeps_recheck_equal_to_cap(self):
        """不传 recheck_interval 时与旧行为一致（成功后间隔 = cap）。"""
        policy = RetryPolicy(cap=300)
        self.assertEqual(policy.recheck_interval, 300)
        policy.on_success(now=1000.0)
        self.assertEqual(policy.next_attempt, 1300.0)

    def test_custom_recheck_interval(self):
        """在线复核可以比失败退避上限短很多（默认 60 秒）。"""
        policy = RetryPolicy(cap=300, recheck_interval=60)
        self.assertEqual(policy.recheck_interval, 60)
        policy.on_success(now=1000.0)
        self.assertEqual(policy.next_attempt, 1060.0)

    def test_zero_recheck_falls_back_to_cap(self):
        policy = RetryPolicy(cap=300, recheck_interval=0)
        self.assertEqual(policy.recheck_interval, 300)

    def test_failure_backoff_steps(self):
        policy = RetryPolicy(cap=300, recheck_interval=60)
        expected = (60, 120, 240, 300, 300)
        for delay in expected:
            policy.on_failure(now=0.0)
            self.assertEqual(policy.next_attempt, float(delay))

    def test_cap_clamps_failure_backoff(self):
        policy = RetryPolicy(cap=30, recheck_interval=60)
        policy.on_failure(now=0.0)
        self.assertEqual(policy.next_attempt, 30.0)

    def test_on_pending_does_not_accumulate_failures(self):
        policy = RetryPolicy(cap=300, recheck_interval=60)
        policy.on_pending(now=0.0)
        self.assertEqual(policy.failures, 1)
        self.assertEqual(policy.next_attempt, 60.0)
        policy.on_pending(now=0.0)
        self.assertEqual(policy.failures, 1)  # 不继续累计，避免快速耗尽档位
        self.assertEqual(policy.next_attempt, 60.0)

    def test_should_try_and_seconds_until_next(self):
        policy = RetryPolicy(cap=300, recheck_interval=60)
        self.assertTrue(policy.should_try(now=0.0))
        policy.on_success(now=100.0)
        self.assertFalse(policy.should_try(now=130.0))
        self.assertEqual(policy.seconds_until_next(now=130.0), 30)

    def test_reset_immediately_allows_retry(self):
        """网络变化事件触发 reset 后应立即复核。"""
        policy = RetryPolicy(cap=300, recheck_interval=60)
        policy.on_failure(now=100.0)
        self.assertFalse(policy.should_try(now=101.0))
        policy.reset()
        self.assertTrue(policy.should_try(now=101.0))
        self.assertEqual(policy.failures, 0)


class AuthStateTests(unittest.TestCase):
    def test_states_distinct(self):
        values = {state.value for state in AuthState}
        self.assertEqual(values, {"online", "offline", "pending", "error"})


if __name__ == "__main__":
    unittest.main()
