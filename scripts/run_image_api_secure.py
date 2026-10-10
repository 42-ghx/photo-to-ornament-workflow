"""Interactive, non-persistent API setup. No key in shell history or arguments."""
import getpass
import os
import sys
import image_api


def main():
    if not sys.stdin.isatty():
        print("请在交互式终端运行；不接受管道输入密钥。", file=sys.stderr)
        return 1
    names = ("ORNAMENT_IMAGE_BASE_URL", "ORNAMENT_IMAGE_MODEL", "ORNAMENT_IMAGE_API_KEY")
    previous = {name: os.environ.get(name) for name in names}
    try:
        print("配置仅保留在本次进程内，不写文件。参考图和提示词会发给你选择的服务商。")
        endpoint = input("API Base URL [https://api.openai.com/v1]: ").strip() or "https://api.openai.com/v1"
        model = input("模型 [gpt-image-1.5]: ").strip() or "gpt-image-1.5"
        key = getpass.getpass("API Key（输入不显示）: ")
        os.environ.update(dict(zip(names, (endpoint, model, key))))
        return image_api.main(sys.argv[1:] or ["--check"])
    except (EOFError, KeyboardInterrupt):
        print("已取消。", file=sys.stderr)
        return 1
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    raise SystemExit(main())
