from .adb import AdbMixin
from .control import ControlMixin
from .instance import InstanceMixin
from .shares import SharesMixin
from .utils import UtilsMixin


class PyMumu(InstanceMixin, ControlMixin, AdbMixin, UtilsMixin, SharesMixin):
    def __init__(self, path: str = None, index: int = 0):
        self.path = path or self._find_mumu()
        self.index = index
        self.shared_folder_path = None

    def __repr__(self):
        return f"PyMumu(path='{self.path}', index={self.index})"
