import json
import os
import time
from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for

from reg_gpt.codex_proxy_service import (
    delete_codex_proxy_account,
    list_codex_proxy_accounts,
    test_codex_proxy_connection,
    upload_batch_accounts,
    upload_single_account,
)
from reg_gpt.cpa_service import (
    cleanup_marked_unusable_remote_accounts,
    delete_remote_accounts,
    get_remote_health_task_status,
    run_remote_health_check,
    start_remote_health_task,
    sync_pending_local_accounts,
    test_cpa_connection,
    toggle_remote_accounts,
    update_remote_account_fields,
)
from reg_gpt.email_weight import reset_all_email_weights, reset_email_weight, set_email_domain_enabled
from reg_gpt.webgui.state import (
    build_cpa_accounts,
    build_cpa_overview,
    build_control_data,
    build_dashboard_data,
    build_logs_data,
    build_results_data,
    read_config,
    read_config_section,
    write_config,
    write_config_section,
)
from reg_gpt.webgui.process_manager import process_manager
from reg_gpt.webgui.security import (
    apply_security_headers,
    get_security_summary,
    get_settings,
    update_security_settings,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(os.path.dirname(BASE_DIR))


def _find_frontend_dist() -> str:
    """查找前端 dist 目录，兼容本地开发和 Docker 部署两种目录结构。"""
    project_root = os.path.dirname(BACKEND_ROOT)
    candidate = os.path.join(project_root, "frontend", "dist")
    if os.path.isdir(candidate):
        return candidate
    candidate = os.path.join(BACKEND_ROOT, "frontend", "dist")
    if os.path.isdir(candidate):
        return candidate
    return candidate


FRONTEND_DIST = _find_frontend_dist()

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
_settings = get_settings()
app.secret_key = _settings.session_secret


@app.after_request
def add_security_headers(response):
    return apply_security_headers(response)


# ─── 旧 Jinja2 页面路由（仅在无新前端时使用） ───


def _nav_items() -> list[dict]:
    return [
        {"endpoint": "dashboard_page", "label": "总览", "match_prefix": "dashboard_"},
        {"endpoint": "config_basic_page", "label": "配置中心", "match_prefix": "config_"},
        {"endpoint": "cpa_overview_page", "label": "CPA管理", "match_prefix": "cpa_"},
        {"endpoint": "security_page", "label": "安全设置", "match_prefix": "security_"},
        {"endpoint": "control_page", "label": "运行控制", "match_prefix": "control_"},
        {"endpoint": "logs_page", "label": "日志监控", "match_prefix": "logs_"},
        {"endpoint": "results_page", "label": "结果概览", "match_prefix": "results_"},
    ]


def _config_tabs() -> list[dict]:
    return [
        {"endpoint": "config_basic_page", "label": "基础配置"},
        {"endpoint": "config_email_page", "label": "邮箱设置"},
        {"endpoint": "config_email_domains_page", "label": "邮箱域名"},
        {"endpoint": "config_network_page", "label": "网络设置"},
        {"endpoint": "config_cpa_page", "label": "CPA连接"},
        {"endpoint": "config_runtime_page", "label": "运行设置"},
    ]


def _cpa_tabs() -> list[dict]:
    return [
        {"endpoint": "cpa_overview_page", "label": "CPA概览"},
        {"endpoint": "cpa_accounts_page", "label": "账号管理"},
        {"endpoint": "cpa_health_page", "label": "健康清理"},
    ]


def _render(page_title: str, template: str, **kwargs):
    return render_template(
        template,
        page_title=page_title,
        nav_items=_nav_items(),
        current_user="",
        **kwargs,
    )


@app.route("/")
def dashboard_page():
    return _render("主程序总览", "dashboard.html")


@app.route("/config")
def config_page():
    return redirect(url_for("config_basic_page"))


@app.route("/config/basic")
def config_basic_page():
    return _render("基础配置", "config_basic.html", config_tabs=_config_tabs())


@app.route("/config/email")
def config_email_page():
    return _render("邮箱设置", "config_email.html", config_tabs=_config_tabs())


@app.route("/config/email-domains")
def config_email_domains_page():
    return _render("邮箱域名", "config_email_domains.html", config_tabs=_config_tabs())


@app.route("/config/network")
def config_network_page():
    return _render("网络设置", "config_network.html", config_tabs=_config_tabs())


@app.route("/config/cpa")
def config_cpa_page():
    return _render("CPA连接", "config_cpa.html", config_tabs=_config_tabs())


@app.route("/config/runtime")
def config_runtime_page():
    return _render("运行设置", "config_runtime.html", config_tabs=_config_tabs())


@app.route("/security")
def security_page():
    return _render("安全设置", "security.html")


@app.route("/control")
def control_page():
    return _render("运行控制", "control.html")


@app.route("/logs")
def logs_page():
    return _render("日志监控", "logs.html")


@app.route("/results")
def results_page():
    return _render("结果概览", "results.html")


@app.route("/cpa")
def cpa_page():
    return redirect(url_for("cpa_overview_page"))


@app.route("/cpa/overview")
def cpa_overview_page():
    return _render("CPA概览", "cpa_overview.html", cpa_tabs=_cpa_tabs())


@app.route("/cpa/accounts")
def cpa_accounts_page():
    return _render("CPA账号管理", "cpa_accounts.html", cpa_tabs=_cpa_tabs())


@app.route("/cpa/health")
def cpa_health_page():
    return _render("CPA健康清理", "cpa_health.html", cpa_tabs=_cpa_tabs())


# ─── JSON API ───


@app.route("/api/dashboard")
def api_dashboard():
    return jsonify(status="success", data=build_dashboard_data())


@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(status="success", config=read_config())


@app.route("/api/config", methods=["POST"])
def api_save_config():
    payload = request.get_json(silent=True) or {}
    config_data = payload.get("config") if isinstance(payload, dict) else None
    if config_data is None:
        config_data = payload
    if not isinstance(config_data, dict):
        return jsonify(status="error", message="请求体必须是 JSON 对象"), 400
    saved = write_config(config_data)
    return jsonify(status="success", message="配置已保存", config=saved)


@app.route("/api/config/<section>", methods=["GET"])
def api_get_config_section(section: str):
    try:
        data = read_config_section(section)
    except KeyError:
        return jsonify(status="error", message="未知配置分区"), 404
    return jsonify(status="success", data=data)


@app.route("/api/config/<section>", methods=["POST"])
def api_save_config_section(section: str):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(status="error", message="请求体必须是 JSON 对象"), 400
    try:
        data = write_config_section(section, payload)
    except KeyError:
        return jsonify(status="error", message="未知配置分区"), 404
    return jsonify(status="success", message="配置已保存", data=data)


@app.route("/api/email/weights/reset", methods=["POST"])
def api_email_weights_reset():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(status="error", message="请求体必须是 JSON 对象"), 400
    reset_all = bool(payload.get("all"))
    try:
        if reset_all:
            result = reset_all_email_weights()
            message = "所有邮箱权重已重置"
        else:
            key = str(payload.get("key") or "").strip()
            if not key:
                return jsonify(status="error", message="key 不能为空"), 400
            result = reset_email_weight(key)
            message = "邮箱权重已重置"
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", message=message, data=result)


@app.route("/api/email/domains/toggle", methods=["POST"])
def api_email_domains_toggle():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(status="error", message="请求体必须是 JSON 对象"), 400
    key = str(payload.get("key") or "").strip()
    if not key:
        return jsonify(status="error", message="key 不能为空"), 400
    enabled = bool(payload.get("enabled", True))
    try:
        result = set_email_domain_enabled(key, enabled=enabled)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", message="域名状态已更新", data=result)


@app.route("/api/results")
def api_results():
    return jsonify(status="success", data=build_results_data())


@app.route("/api/cpa/overview")
def api_cpa_overview():
    return jsonify(status="success", data=build_cpa_overview())


@app.route("/api/cpa/accounts")
def api_cpa_accounts():
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = max(1, int(request.args.get("per_page", 50)))
    except (TypeError, ValueError):
        per_page = 50
    health_status = str(request.args.get("health_status", "") or "").strip().lower()
    provider = str(request.args.get("provider", "") or "").strip().lower()
    disabled_state = str(request.args.get("disabled_state", "") or "").strip().lower()
    keyword = str(request.args.get("keyword", "") or "").strip()
    force_reload = str(request.args.get("force_reload", "")).strip().lower() in {"1", "true", "yes", "on"}
    return jsonify(
        status="success",
        data=build_cpa_accounts(
            page=page,
            per_page=per_page,
            health_status=health_status,
            provider=provider,
            disabled_state=disabled_state,
            keyword=keyword,
            force_reload=force_reload,
        ),
    )


@app.route("/api/cpa/test", methods=["POST"])
def api_cpa_test():
    try:
        data = test_cpa_connection(force_reload=True)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data=data)


@app.route("/api/cpa/sync", methods=["POST"])
def api_cpa_sync():
    payload = request.get_json(silent=True) or {}
    try:
        limit = max(0, int((payload or {}).get("limit") or 0))
    except (TypeError, ValueError):
        limit = 0
    try:
        data = sync_pending_local_accounts(limit=limit, force_reload=True)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data=data)


@app.route("/api/cpa/health/check", methods=["POST"])
def api_cpa_health_check():
    payload = request.get_json(silent=True) or {}
    names = payload.get("names") if isinstance(payload, dict) else None
    if names is not None and not isinstance(names, list):
        return jsonify(status="error", message="names 必须是数组"), 400
    try:
        data = run_remote_health_check(names=names or None, force_reload=True)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data=data)


@app.route("/api/cpa/health/start", methods=["POST"])
def api_cpa_health_start():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(status="error", message="请求体必须是 JSON 对象"), 400
    names = payload.get("names")
    cleanup = bool(payload.get("cleanup"))
    if names is not None and not isinstance(names, list):
        return jsonify(status="error", message="names 必须是数组"), 400
    try:
        data = start_remote_health_task(names=names or None, cleanup=cleanup, force_reload=True)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data=data)


@app.route("/api/cpa/health/status")
def api_cpa_health_status():
    try:
        data = get_remote_health_task_status()
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data=data)


@app.route("/api/cpa/health/cleanup", methods=["POST"])
def api_cpa_health_cleanup():
    payload = request.get_json(silent=True) or {}
    names = payload.get("names") if isinstance(payload, dict) else None
    if names is not None and not isinstance(names, list):
        return jsonify(status="error", message="names 必须是数组"), 400
    try:
        data = cleanup_marked_unusable_remote_accounts(names=names or None, force_reload=True)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data=data)


@app.route("/api/cpa/accounts/delete", methods=["POST"])
def api_cpa_accounts_delete():
    payload = request.get_json(silent=True) or {}
    names = payload.get("names") if isinstance(payload, dict) else None
    if not isinstance(names, list) or not names:
        return jsonify(status="error", message="请至少传入一个账号名"), 400
    try:
        data = delete_remote_accounts(names=names, force_reload=True)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data=data)


@app.route("/api/cpa/accounts/toggle", methods=["POST"])
def api_cpa_accounts_toggle():
    payload = request.get_json(silent=True) or {}
    names = payload.get("names") if isinstance(payload, dict) else None
    disabled = bool((payload or {}).get("disabled")) if isinstance(payload, dict) else False
    if not isinstance(names, list) or not names:
        return jsonify(status="error", message="请至少传入一个账号名"), 400
    try:
        data = toggle_remote_accounts(names=names, disabled=disabled, force_reload=True)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data=data)


@app.route("/api/cpa/accounts/fields", methods=["POST"])
def api_cpa_accounts_fields():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(status="error", message="请求体必须是 JSON 对象"), 400
    name = str(payload.get("name") or "").strip()
    if not name:
        return jsonify(status="error", message="name 不能为空"), 400

    priority_raw = payload.get("priority")
    priority = None
    if priority_raw not in (None, ""):
        try:
            priority = int(priority_raw)
        except (TypeError, ValueError):
            return jsonify(status="error", message="priority 必须是数字"), 400

    note = payload.get("note")
    if note is not None:
        note = str(note)

    try:
        data = update_remote_account_fields(name=name, priority=priority, note=note, force_reload=True)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data=data)


# ─── CodexProxy API ───


@app.route("/api/codex-proxy/test", methods=["POST"])
def api_codex_proxy_test():
    try:
        data = test_codex_proxy_connection(force_reload=True)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data=data)


@app.route("/api/codex-proxy/accounts")
def api_codex_proxy_accounts():
    try:
        accounts = list_codex_proxy_accounts(force_reload=True)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data={"accounts": accounts, "total": len(accounts)})


@app.route("/api/codex-proxy/upload", methods=["POST"])
def api_codex_proxy_upload():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(status="error", message="请求体必须是 JSON 对象"), 400

    # 批量模式：refresh_tokens 用换行分隔
    refresh_tokens = str(payload.get("refresh_tokens") or "").strip()
    if refresh_tokens:
        name_prefix = str(payload.get("name_prefix") or "reg").strip()
        proxy_url = str(payload.get("proxy_url") or "").strip()
        try:
            data = upload_batch_accounts(
                refresh_tokens=refresh_tokens,
                name_prefix=name_prefix,
                proxy_url=proxy_url,
                force_reload=True,
            )
        except Exception as exc:
            return jsonify(status="error", message=str(exc)), 400
        return jsonify(status="success", data=data)

    # 单个模式
    name = str(payload.get("name") or "").strip()
    refresh_token = str(payload.get("refresh_token") or "").strip()
    if not name or not refresh_token:
        return jsonify(status="error", message="name 和 refresh_token 不能为空"), 400
    proxy_url = str(payload.get("proxy_url") or "").strip()
    try:
        data = upload_single_account(name=name, refresh_token=refresh_token, proxy_url=proxy_url, force_reload=True)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data=data)


@app.route("/api/codex-proxy/accounts/delete", methods=["POST"])
def api_codex_proxy_delete():
    payload = request.get_json(silent=True) or {}
    name = str((payload or {}).get("name") or "").strip()
    if not name:
        return jsonify(status="error", message="name 不能为空"), 400
    try:
        data = delete_codex_proxy_account(name, force_reload=True)
    except Exception as exc:
        return jsonify(status="error", message=str(exc)), 400
    return jsonify(status="success", data=data)


@app.route("/api/security", methods=["GET"])
def api_security():
    return jsonify(status="success", data=get_security_summary())


@app.route("/api/security", methods=["POST"])
def api_security_save():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(status="error", message="请求体必须是 JSON 对象"), 400
    result = update_security_settings(payload)
    return jsonify(status="success", message="安全配置已更新", data=result)


@app.route("/api/logs")
def api_logs():
    try:
        limit = max(20, min(1000, int(request.args.get("limit", 200))))
    except (TypeError, ValueError):
        limit = 200
    return jsonify(status="success", data=build_logs_data(limit=limit))


@app.route("/api/control")
def api_control():
    return jsonify(status="success", data=build_control_data())


@app.route("/api/control/stream")
def api_control_stream():
    """SSE 端点：实时推送运行控制状态。"""

    def generate():
        last_hash = ""
        while True:
            try:
                data = build_control_data()
                # 用 updated_at 作为变化检测，避免每次都序列化完整数据做对比
                current_hash = str(data.get("updated_at", "")) + str(data.get("successes", 0)) + str(data.get("failures", 0))
                if current_hash != last_hash:
                    last_hash = current_hash
                    payload = json.dumps({"status": "success", "data": data}, ensure_ascii=False, separators=(",", ":"))
                    yield f"data: {payload}\n\n"
            except Exception:
                pass
            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/api/control/start", methods=["POST"])
def api_control_start():
    result = process_manager.start()
    code = 200 if result.get("ok") else 400
    payload = dict(result)
    payload["status"] = "success" if result.get("ok") else "error"
    return jsonify(payload), code


@app.route("/api/control/stop", methods=["POST"])
def api_control_stop():
    result = process_manager.stop()
    code = 200 if result.get("ok") else 400
    payload = dict(result)
    payload["status"] = "success" if result.get("ok") else "error"
    return jsonify(payload), code


@app.route("/api/control/restart", methods=["POST"])
def api_control_restart():
    stop_result = process_manager.stop()
    start_result = process_manager.start()
    ok = bool(start_result.get("ok"))
    code = 200 if ok else 400
    return jsonify(
        status="success" if ok else "error",
        ok=ok,
        message="主程序已重启" if ok else start_result.get("message", "重启失败"),
        stop_result=stop_result,
        start_result=start_result,
        status_info=process_manager.status(),
    ), code


@app.route("/api/control/logs/delete", methods=["POST"])
def api_control_logs_delete():
    result = process_manager.clear_log()
    code = 200 if result.get("ok") else 400
    payload = dict(result)
    payload["status"] = "success" if result.get("ok") else "error"
    return jsonify(payload), code


# ─── 新前端 SPA 托管 ───


if os.path.isdir(FRONTEND_DIST):
    from flask import send_from_directory

    _USE_NEW_FRONTEND = True

    @app.route("/app/")
    @app.route("/app/<path:path>")
    def serve_frontend(path=""):
        if path and os.path.isfile(os.path.join(FRONTEND_DIST, path)):
            return send_from_directory(FRONTEND_DIST, path)
        return send_from_directory(FRONTEND_DIST, "index.html")

    @app.route("/assets/<path:path>")
    def serve_frontend_assets(path):
        return send_from_directory(os.path.join(FRONTEND_DIST, "assets"), path)
else:
    _USE_NEW_FRONTEND = False


@app.before_request
def _redirect_to_spa():
    """新前端存在时，将旧页面路由重定向到 SPA。"""
    if not _USE_NEW_FRONTEND:
        return None
    path = request.path
    if path.startswith(("/api/", "/app/", "/assets/", "/static/")):
        return None
    if request.method != "GET":
        return None
    if path in ("/", "/login", "/config", "/control", "/logs", "/results",
                 "/security", "/cpa", "/cpa/overview", "/cpa/accounts", "/cpa/health") \
       or path.startswith(("/config/", "/cpa/")):
        return redirect("/app/")


def main() -> None:
    settings = get_settings()
    app.run(host=settings.host, port=settings.port, debug=False)


if __name__ == "__main__":
    main()
