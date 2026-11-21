"""colormap 核心 API（初始未实现）。"""


class ColorMap:
    def __init__(self, stops, levels=256):
        """构造"""
        raise NotImplementedError

    def lookup(self, t):
        """查表"""
        raise NotImplementedError

    def validate(self):
        """单调校验"""
        raise NotImplementedError
