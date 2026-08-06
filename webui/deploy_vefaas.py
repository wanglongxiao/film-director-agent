# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""把 aw-director-agent Web UI（BFF）部署到火山引擎 VeFaaS。

用法：
    .venv/bin/python webui/deploy_vefaas.py

前置：`.env` 中需具备
    VOLCENGINE_ACCESS_KEY / VOLCENGINE_SECRET_KEY   （部署鉴权 + 注入到函数）
    CLOUD_AGENT_API_KEY                              （云端 Agent apikey，服务端保管）
可选：
    CLOUD_AGENT_BASE_URL（默认已内置用户给定域名）
    WEBUI_ENABLE_LOCAL=false                         （云端环境无本地 :8000，建议关闭本地目标）
    WEBUI_APP_NAME                                   （VeFaaS 应用名，默认 aw-director-webui；不能含下划线）

说明：
- VeFaaS 会把 `veadk.config.veadk_environments`（即 .env 内容）注入为函数环境变量，
  因此 CLOUD_AGENT_API_KEY 等仅存在于服务端，不写入前端 bundle。
- bundle 目录为 webui/ 本身（含 run.sh / requirements.txt / server.py / static/）。
"""

from __future__ import annotations

import os
from pathlib import Path

import veadk.config
from veadk.config import getenv
from veadk.integrations.ve_faas.ve_faas import VeFaaS

HERE = Path(__file__).resolve().parent


def main() -> None:
    ak = getenv("VOLCENGINE_ACCESS_KEY", "", allow_false_values=True)
    sk = getenv("VOLCENGINE_SECRET_KEY", "", allow_false_values=True)
    if not ak or not sk:
        raise SystemExit("VOLCENGINE_ACCESS_KEY / VOLCENGINE_SECRET_KEY 未配置于 .env")

    app_name = os.getenv("WEBUI_APP_NAME", "aw-director-webui")
    if "_" in app_name:
        raise SystemExit("VeFaaS 应用名不能包含下划线：" + app_name)

    faas = VeFaaS(access_key=ak, secret_key=sk, region="cn-beijing")

    # 已存在则原地更新代码并重新发布，保留原 URL；否则全新部署。
    existing = faas.find_app_id_by_name(app_name)
    if existing:
        print(f"应用 {app_name} 已存在（{existing}），更新代码并重新发布…")
        # 用 update_application_code_bundle 直接上传 webui/（含 run.sh），
        # 避开 _update_function_code 里 cookiecutter 写 ~/.cookiecutter_replay 的限制。
        route = faas.get_application_details(app_id=existing)
        import json as _json

        cloud_resource = _json.loads(route["CloudResource"])
        fn_id = cloud_resource["framework"]["function"]["Id"]
        # 对已有应用更新时，显式把当前 .env 合并进函数环境变量；
        # 否则新增的 WEBUI_ACCESS_PASSWORD 之类配置不会随代码 bundle 更新。
        env_overrides = dict(veadk.config.veadk_environments)
        url = faas.update_application_code_bundle(
            application_id=existing,
            function_id=fn_id,
            path=str(HERE),
            environment_overrides=env_overrides,
        )
        app_id = existing
    else:
        print(f"首次部署 VeFaaS 应用 {app_name} …")
        url, app_id, fn_id = faas.deploy(name=app_name, path=str(HERE))

    print("\n==== 部署完成 ====")
    print(f"Application: {app_name}  (id={app_id}, fn={fn_id})")
    print(f"Web UI URL : {url}")


if __name__ == "__main__":
    main()
