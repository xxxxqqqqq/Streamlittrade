"""验证核心包不会重新依赖界面框架。"""

import ast
import unittest
from pathlib import Path

import pandas as pd

from quant_core.strategy_runtime import resolve_strategy


class CoreBoundaryTests(unittest.TestCase):
    def test_quant_core_does_not_import_streamlit(self):
        core_dir = Path(__file__).parents[1] / "quant_core"
        offenders = []
        for path in core_dir.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported = []
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = [node.module]
                if any(name == "streamlit" or name.startswith("streamlit.") for name in imported):
                    offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_custom_strategy_requires_explicit_trust(self):
        code = "def generate_signal(df):\n    return df"
        with self.assertRaises(PermissionError):
            resolve_strategy("自定义策略", custom_code=code)

    def test_trusted_strategy_can_use_its_imports(self):
        code = (
            "import numpy as np\n"
            "def generate_signal(df):\n"
            "    result = df.copy()\n"
            "    result['signal'] = np.array([False] * len(df))\n"
            "    return result\n"
        )
        strategy, _, _ = resolve_strategy(
            "自定义策略", custom_code=code, trusted_code=True
        )
        result = strategy(pd.DataFrame({"close": [1, 2]}))
        self.assertEqual(result["signal"].tolist(), [False, False])


if __name__ == "__main__":
    unittest.main()
