import argparse
import json
import os
import socket
import sys
import urllib.request
import urllib.error

import uvicorn

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
CONFIG_FILE = "server_config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VGD Memory OS — Graph-Document Hybrid Demo 服务启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python run.py                                             # 默认 0.0.0.0:8000\n"
            "  python run.py --host 127.0.0.1 --port 8080                # 自定义地址和端口\n"
            "  python run.py --port 9000 --auto-port                      # 指定端口，被占用时自动分配\n"
            "  python run.py --config my_server.json                     # 从配置文件读取\n"
        ),
    )
    parser.add_argument("--host", type=str, default=None, help=f"服务监听地址 (默认: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=None, help=f"服务监听端口 (默认: {DEFAULT_PORT})")
    parser.add_argument("--config", type=str, default=CONFIG_FILE,
                        help=f"JSON 配置文件路径 (默认: {CONFIG_FILE})")
    parser.add_argument("--no-reload", action="store_true", help="禁用代码热重载 (默认: 启用)")
    parser.add_argument("--auto-port", action="store_true",
                        help="端口被占用时自动分配一个可用端口")
    return parser.parse_args()


def load_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print(f"[警告] 配置文件 {config_path} 格式错误：顶层须为 JSON 对象，将忽略。")
            return {}
        print(f"[配置] 已加载配置文件: {config_path}")
        return data
    except json.JSONDecodeError as e:
        print(f"[警告] 配置文件 {config_path} JSON 解析失败: {e}")
        print(f"[警告] 将忽略配置文件，使用命令行参数或默认值。")
        return {}
    except IOError as e:
        print(f"[警告] 配置文件 {config_path} 读取失败: {e}")
        return {}


def resolve_config(args: argparse.Namespace, config: dict) -> tuple[str, int, bool]:
    host = args.host or config.get("host", DEFAULT_HOST)
    port = args.port or config.get("port", DEFAULT_PORT)
    reload_enabled = not args.no_reload
    return host, port, reload_enabled


def check_port_available(host: str, port: int) -> bool:
    check_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        try:
            sock.bind((check_host, port))
            sock.close()
            return True
        except OSError:
            return False


def find_available_port(host: str, start_port: int, max_attempts: int = 100) -> int:
    check_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            try:
                sock.bind((check_host, port))
                sock.close()
                return port
            except OSError:
                continue
    return -1


def print_port_error(host: str, port: int) -> None:
    print()
    print("=" * 60)
    print(f"  [错误] 端口 {port} 已被占用，无法启动服务！")
    print("=" * 60)
    print()
    print(f"  地址 {host}:{port} 当前已被其他进程占用。")
    print()
    print("  [解决方案]")
    print(f"    方案一：指定其他端口")
    print(f"      python run.py --port {port + 1}")
    print()
    print(f"    方案二：自动分配可用端口")
    print(f"      python run.py --port {port} --auto-port")
    print()
    print("    方案三：查找并释放占用端口的进程")
    if sys.platform == "win32":
        print(f"      netstat -ano | findstr :{port}")
        print(f"      taskkill /PID <进程ID> /F")
    else:
        print(f"      lsof -i :{port}")
        print(f"      kill -9 <PID>")
    print()


def print_startup_banner(host: str, port: int, reload_enabled: bool) -> None:
    display_host = "localhost" if host == "0.0.0.0" else host
    print()
    print("=" * 60)
    print("  VGD Memory OS — Graph-Document Hybrid Demo")
    print("=" * 60)
    print()
    print(f"  [地址]   http://{display_host}:{port}")
    print(f"  [重载]   {'已启用' if reload_enabled else '已禁用'}")
    print()
    print(f"  在浏览器中打开上述地址以访问 VGD 控制台。")
    print()


def _mask(value: str, visible: int = 4) -> str:
    if len(value) <= visible + 4:
        return value[:visible] + "****"
    return value[:visible] + "****" + value[-visible:]


def _set_env(env_key: str, value: str, sensitive: bool = False) -> None:
    if not value:
        return
    os.environ[env_key] = str(value)
    readback = os.environ.get(env_key, "")
    if readback == str(value):
        display = _mask(readback) if sensitive else readback
        print(f"[配置] {env_key}={display}")
    else:
        print(f"[警告] {env_key} 设置失败")


PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
LLM_ENV_MAP = {
    PROVIDER_ANTHROPIC: {"base_url": "ANTHROPIC_BASE_URL", "api_key": "ANTHROPIC_API_KEY"},
    PROVIDER_OPENAI: {"base_url": "OPENAI_BASE_URL", "api_key": "OPENAI_API_KEY"},
}
MODEL_ENV_MAP = {
    "extract": "VGD_EXTRACT_MODEL",
    "wiki": "VGD_WIKI_MODEL",
    "reason": "VGD_REASON_MODEL",
}


def apply_llm_config(config: dict) -> None:
    llm_cfg = config.get("llm")
    if not llm_cfg or not isinstance(llm_cfg, dict):
        return

    provider = llm_cfg.get("provider", PROVIDER_ANTHROPIC)
    if provider:
        os.environ["LLM_PROVIDER"] = str(provider)
        print(f"[配置] LLM 提供商: {provider}")

    env_map = LLM_ENV_MAP.get(provider, LLM_ENV_MAP[PROVIDER_ANTHROPIC])
    for cfg_key, env_key in env_map.items():
        _set_env(env_key, llm_cfg.get(cfg_key) or "", sensitive=(cfg_key == "api_key"))

    ssl_verify = llm_cfg.get("ssl_verify")
    if ssl_verify is not None:
        os.environ["OPENAI_SSL_VERIFY"] = str(ssl_verify).lower()
        print(f"[配置] OPENAI_SSL_VERIFY={str(ssl_verify).lower()}")

    models = llm_cfg.get("models")
    if models and isinstance(models, dict):
        for cfg_key, env_key in MODEL_ENV_MAP.items():
            _set_env(env_key, models.get(cfg_key) or "")


def check_llm_connectivity() -> None:
    provider = os.environ.get("LLM_PROVIDER", PROVIDER_ANTHROPIC)
    if provider == PROVIDER_OPENAI:
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    else:
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

    print(f"[诊断] 测试 LLM API 连通性: {base_url}")
    url = base_url.rstrip("/")

    import ssl
    ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "VGD-Demo/1.0")
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        print(f"[诊断] ✅ {url} → HTTP {resp.status} ({resp.reason})")
        resp.close()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[诊断] ⚠️  {url} → HTTP 404 (该端点不支持 GET，这通常是正常的)")
        elif e.code in (400, 401, 403):
            print(f"[诊断] ⚠️  {url} → HTTP {e.code} (服务器可达，但 GET 被拒绝)")
        else:
            print(f"[诊断] ⚠️  {url} → HTTP {e.code} (服务器可达)")
    except urllib.error.URLError as e:
        err_str = str(e.reason)
        if "certificate verify failed" in err_str or "CERTIFICATE_VERIFY_FAILED" in err_str:
            print(f"[诊断] ❌ SSL 证书验证失败: {err_str}")
            print(f"[诊断]    原因: 企业网络代理拦截了 HTTPS 连接（自签名证书）")
            print(f"[诊断]    修复: 在 server_config.json 中设置 \"ssl_verify\": false")
        else:
            print(f"[诊断] ❌ {url} → 无法连接: {err_str}")
            print(f"[诊断]    建议: 1) ping 检查网络; 2) 检查代理设置; 3) 更换可用 API")
    except ssl.SSLError as e:
        print(f"[诊断] ❌ SSL 错误: {e}")
        print(f"[诊断]    原因: 企业网络代理拦截了 HTTPS 连接（自签名证书）")
        print(f"[诊断]    修复: 在 server_config.json 中设置 \"ssl_verify\": false")
    except socket.timeout:
        print(f"[诊断] ❌ {url} → 连接超时 (10s)")
        print(f"[诊断]    建议: 网络环境可能无法直接访问该 API，请考虑切换至可用后端")
    except Exception as e:
        print(f"[诊断] ❌ {url} → {type(e).__name__}: {e}")
    print()


if __name__ == "__main__":
    args = parse_args()
    config = load_config(args.config)
    host, port, reload_enabled = resolve_config(args, config)

    apply_llm_config(config)

    check_llm_connectivity()

    if not check_port_available(host, port):
        print_port_error(host, port)

        if args.auto_port:
            new_port = find_available_port(host, port + 1)
            if new_port == -1:
                print(f"  [错误] 在端口范围 {port + 1}-{port + 100} 内未找到可用端口。")
                print(f"  [错误] 请手动指定一个未被占用的端口。")
                sys.exit(1)
            print(f"  [自动分配] 已自动分配可用端口: {new_port}")
            print()
            port = new_port
        else:
            sys.exit(1)

    print_startup_banner(host, port, reload_enabled)
    uvicorn.run("api.app:app", host=host, port=port, reload=reload_enabled)
