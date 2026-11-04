# macOS 打包

生成 arm64 `.app`、`.dmg` 和 zip：

```bash
cd /Users/zjq/vibe/birdClass
.venv/bin/pip install 'pyinstaller>=6,<7'
./packaging/build_macos.sh
```

产物：

```text
dist/羽栖 BirdRoost.app
dist/羽栖 BirdRoost.dmg
dist/羽栖 BirdRoost-macOS-arm64.zip
```

说明：

- 使用 PyInstaller `--windowed` 打包。
- 内置 IOC 名录、地区表、应用图标和 Python 依赖。
- 构建脚本会对 app 做 ad-hoc 签名，便于本机运行。
- 没有 Developer ID 证书，因此分享给其他 Mac 时首次打开可能需要右键 → 打开，或执行：

```bash
xattr -dr com.apple.quarantine "/Applications/羽栖 BirdRoost.app"
```

- DMG 内含应用和 Applications 快捷方式，打开后把应用拖入 Applications 即可。
- 当前产物为 Apple silicon（arm64）；Intel Mac 需要在 Intel 环境重新构建。
- 若需正式分发，需要 Apple Developer ID 签名和 notarization。
