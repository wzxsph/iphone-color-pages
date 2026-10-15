# iPhone Color Pages

通过 Mac、USB 数据线和苹果的 `cfgutil`，把 iPhone 主屏幕按图标颜色整理成每页一种颜色。先在本地查看图标联系表、修正颜色，再应用经过检查的布局。

[English](README.md) · [详细用法](docs/usage.md) · [安全边界与限制](docs/safety-and-limitations.md)

**应用前请先阅读限制。** `cfgutil` 的图标布局快照不能完整表示小组件和同一 App 的重复主屏幕入口。整理后可能需要重新添加小组件，快照也不能保证无损回滚。

## 环境要求

- Mac；[Apple Configurator 的 App Store 页面](https://apps.apple.com/us/app/apple-configurator/id1037126344?mt=12)目前要求 macOS 15.7 或更新版本。
- Apple Configurator 及其命令行工具 `cfgutil`；本流程基于 2.21 版本开发。
- 用 USB 连接、已解锁并信任这台 Mac 的 iPhone。
- Python 3.10 或更新版本；安装项目时会安装 Pillow。

在 Mac App Store 安装 Apple Configurator。CLI 会自动查找应用内的 `/Applications/Apple Configurator.app/Contents/MacOS/cfgutil`，可用 `"/Applications/Apple Configurator.app/Contents/MacOS/cfgutil" version` 检查；将自动化工具安装到 `PATH` 是可选步骤。如果要指定其他路径，须把全局参数 `--cfgutil /path/to/cfgutil` 放在**子命令之前**。底层功能可参考苹果的[主屏幕布局说明](https://support.apple.com/guide/apple-configurator-mac/cadbf9c2a0/mac)。

底层 `cfgutil` 方法有 **iOS 27.0.1 的一次真机实测**；本仓库可复用 CLI 仅经过合成数据和模拟设备测试，尚未用真机验证。不能据此保证其他设备或 iOS 版本兼容。

## 安装与无设备预览

```sh
git clone https://github.com/wzxsph/iphone-color-pages.git
cd iphone-color-pages
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

# 仅生成合成图标示例，不需要连接手机。
iphone-color-pages demo --output .local/demo
```

也可以用等价的模块入口：`python -m iphone_color_pages …`。

![合成图标的颜色分页预览](docs/assets/demo.png)

预览使用合成图标和数据，不是手机截图。

## 整理手机

将 `<ECID>` 换成 `devices` 显示的设备标识。`scan` 要求使用新的空会话目录；把会话和个人文件放在 `.local/` 下，避免提交到公开仓库。

```sh
python -m iphone_color_pages devices
python -m iphone_color_pages scan --ecid <ECID> --session .local/my-phone
python -m iphone_color_pages plan --session .local/my-phone
```

检查会话中的 `preview.png`、`contact-sheets/icons-001.png` 及后续联系表、`plan.json` 和 `scan-report.json`。自动分类只使用本地 HSV 图像分析，是粗略初稿；白底、暗色、渐变和多色图标尤其需要人工检查。缺失或无法读取的图标以及网页快捷方式默认归入 `multicolor`，这些待检查项本身不会阻止 `apply`。可以用以 bundle identifier 为键的 JSON 对象覆盖颜色：

```json
{
  "com.example.reader": "blue",
  "com.example.notes": "white"
}
```

```sh
python -m iphone_color_pages plan --session .local/my-phone --overrides .local/overrides.json
python -m iphone_color_pages apply --session .local/my-phone --accept-widget-changes
python -m iphone_color_pages verify --session .local/my-phone
```

`apply` 会在终端显示实际设备和入口数量，要求交互确认。非交互运行必须显式传入 `--yes`；它不会代替 `--accept-widget-changes`，也不会跳过校验。

`devices`、`scan`、`snapshot`、`plan`、`verify` 和 `demo` 都不会向手机写入主屏幕布局。**只有 `apply` 会写入布局。** 写入前会重新读取设备，要求当前布局与规划基线完全匹配；写入前后保存快照，并检查 App 入口计数、Dock、文件夹和页面。如果设备已与方案一致，则只校验、不再写入。失败后不会自动重试写入或恢复布局。

## 分页规则

支持 `red`、`orange`、`yellow`、`green`、`teal`、`blue`、`purple`、`pink`、`black`、`gray`、`white`、`multicolor` 共 12 种分类，每种用到的颜色单独一页。超出页面容量的 App 放入同色文件夹，每个文件夹内页放 9 个图标。Dock 保持原有布局。`plan --page-capacity` 默认每页 24 个可见位置；如果屏幕布局容量较小，可用 `--page-capacity 20` 等值重新规划，并再次检查预览。

真机实测中，iOS 曾在写入后把 App 资源库中的额外 App 插入主屏幕。发现额外入口时校验会失败，需要主动重新读取、规划、检查，再应用。详见[重新规划步骤](docs/usage.md#when-verification-fails)。

## 本地数据与开发

分类由 Python 和 Pillow 在本地完成，不使用 OpenAI API、其他 AI 服务、API 密钥、云端上传或遥测。安装依赖时可能访问 Python 软件包索引。

最初的单设备整理使用了 AI 辅助视觉归类和人工修正；开源 CLI 改用 HSV 建议和手工覆盖，不能自动完整复现当时的视觉判断。

公开仓库只包含合成示例。设备标识、App 清单、导出的图标、布局快照和联系表属于个人数据，请勿提交。App 图标版权归各权利人所有。

运行测试：

```sh
python -m unittest discover -s tests
```

参见 [CONTRIBUTING.md](CONTRIBUTING.md)。项目代码采用 [MIT 许可证](LICENSE)，本项目独立于苹果。
