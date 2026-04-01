import pytest
import hashlib


class TestABTestGrouping:
    def test_deterministic_same_session_same_group(self, svc):
        session_id = "any-fixed-session-id"
        h = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
        expected = "control" if h % 10 == 0 else "treatment"

        import asyncio

        async def get_group(sid):
            _, meta = await svc.search("test", session_id=sid, enable_ab_test=True)
            return meta["ab_test_group"]

        loop = asyncio.new_event_loop()
        try:
            group1 = loop.run_until_complete(get_group(session_id))
            group2 = loop.run_until_complete(get_group(session_id))
        finally:
            loop.close()
        assert group1 == expected
        assert group2 == expected

    def test_10_percent_control_distribution(self):
        control_count = 0
        total = 1000
        for i in range(total):
            h = int(hashlib.md5(f"session-{i}".encode()).hexdigest(), 16)
            if h % 10 == 0:
                control_count += 1
        ratio = control_count / total
        assert 0.05 <= ratio <= 0.15, f"Control 比例应接近 10%，实际 {ratio:.1%}"

    def test_no_session_id_defaults_to_treatment(self, svc):
        import asyncio

        async def run():
            _, meta = await svc.search("test", session_id=None, enable_ab_test=True)
            return meta

        loop = asyncio.new_event_loop()
        try:
            meta = loop.run_until_complete(run())
        finally:
            loop.close()
        assert meta["ab_test_group"] == "treatment"
        assert meta["show_results"] is True
