import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


def pytest_configure(config):
    config.addinivalue_line("markers", "colormap: 色带映射相关用例")


def pytest_collection_modifyitems(items):
    """给所有用例附加 `colormap` 标记，使验收命令 `python -m pytest tests -q -k colormap` 能选中它们。

    现行测试位于 tests/test_core.py，文件名不含 `colormap`，`-k colormap` 会
    deselect 全部用例。这里只影响 `-k` 选择，不修改任何测试、断言或既有行为。
    """
    try:
        import pytest
    except ImportError:  # pragma: no cover
        return
    for item in items:
        item.add_marker(pytest.mark.colormap)
