def test_scheduler_module_importable():
    from src.scheduler import build_scheduler
    s = build_scheduler(backend=None, command_bus=None)
    assert s is not None


def test_scheduler_has_two_jobs():
    from src.scheduler import build_scheduler
    s = build_scheduler(backend=None, command_bus=None)
    jobs = s.get_jobs()
    assert len(jobs) == 2
