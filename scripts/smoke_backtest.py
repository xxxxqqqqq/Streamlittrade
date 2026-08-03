"""对运行中的量化平台执行一次端到端异步回测。

仅使用Python标准库，适合开发者在容器重建或服务器部署后快速确认：API提交、
Redis排队、Worker计算和PostgreSQL结果查询均正常。
"""

from __future__ import annotations

import argparse
import json
import time
from urllib.request import Request, urlopen


def request_json(url: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="量化平台异步回测冒烟测试")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    submission = request_json(
        f"{args.base_url}/api/v1/backtests",
        method="POST",
        body={
            "data_source": "demo",
            "symbol": "DEMO",
            "strategy_name": "right_trend",
            "strategy_parameters": {
                "ma_short": 5,
                "ma_mid": 20,
                "ma_long": 60,
                "vol_ratio": 1.2,
            },
            "start_date": "2020-01-01",
            "end_date": "2024-12-31",
            "initial_cash": 100000,
        },
    )
    print(f"任务已提交: {submission['job_id']}")

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        job = request_json(f"{args.base_url}/api/v1/jobs/{submission['job_id']}")
        print(f"状态={job['status']} 进度={job['progress']:.0f}%")
        if job["status"] == "succeeded":
            result = request_json(
                f"{args.base_url}/api/v1/backtests/{submission['backtest_id']}"
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if job["status"] == "failed":
            raise RuntimeError(job.get("error_message") or "回测任务失败")
        time.sleep(0.5)
    raise TimeoutError(f"任务在{args.timeout}秒内未完成")


if __name__ == "__main__":
    main()
