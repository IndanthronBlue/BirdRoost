# 羽栖 BirdRoost · Android 只读客户端

小米/Android 手机只读图库。直接读取腾讯云 COS 上的 BirdRoost manifest、缩略图和原图，不需要桌面端或后端在线。

## 功能

- 输入只读 COS 配置：Bucket、Region、Prefix、SecretId、SecretKey
- SecretId/SecretKey 使用 Android Keystore + AES/GCM 加密保存
- 读取 `users/<prefix>/manifest.json`
- 内联搜索联想：物种 / 地点 / 时间 / 学名（不抢输入焦点，键盘收起自动隐藏）
- 分类树抽屉：界/门/纲/目/科/属/种层级
- 特殊照片单独分组：非鸟动物 / 风景 / 待复核
- 传统名/别名映射
- 按分类节点筛选、按物种/地点/时间搜索
- 网格浏览 256 WebP 缩略图
- 点开大图查看原图
- 下载原图到系统相册 `Pictures/BirdRoost/`
- 无上传、无删除、无纠错写操作

## 安全

请使用**只读 COS 子账号**，只授予：

```text
cos:GetObject
cos:HeadObject
```

不要给手机端 PutObject / DeleteObject 权限。

## 构建

需要 JDK 17 + Android SDK 35：

```bash
cd mobile/android
export JAVA_HOME=/path/to/jdk17
export ANDROID_HOME=/path/to/android-sdk
./gradlew assembleDebug
```

APK：

```text
app/build/outputs/apk/debug/app-debug.apk
```

## 安装

```bash
adb install -r app-debug.apk
```

当前 APK 是 debug 签名，适合自用测试，不适合上架。保存原图到相册需要 Android 10+。
