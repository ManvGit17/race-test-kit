import _common


def pytest_sessionfinish(session, exitstatus):  # type: ignore[no-untyped-def]
    _common.write_out()
