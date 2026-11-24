"""SPA API 层加载时序回归测试

回归对象：frontend/api/client.js 的 axios 等待逻辑（此前同步执行时
window.axios 未就绪 → TypeError → window.apiClient 从未挂载，
整个 SPA 的 API 层不可用）。通过 Node 模拟浏览器加载时序验证。
"""
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_client_js_waits_for_axios_and_mounts_api_client():
    """axios 未就绪时不抛错；就绪后 apiClient 挂载且 CSRF 拦截器生效。"""
    result = subprocess.run(
        ['node', 'tests/spa_client_smoke.mjs'],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=60,
    )
    print(result.stdout)
    assert result.returncode == 0, f'Node 冒烟测试失败:\n{result.stderr}'
    assert 'ALL SPA CLIENT TESTS PASSED' in result.stdout
