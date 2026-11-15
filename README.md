## CCTV_Toolkit
A simple tool helps you record HQ CCTV channel

## 文件说明

| 文件 | 说明 |
|---|---|
| `av3a2aac-ac3.pyw` | 主程序源码（Python 3 + ttkbootstrap） |
| `requirements.txt` | 运行/打包依赖 |
| `build.ps1` | 一键重新打包 EXE 的脚本 |

## 运行（源码方式）

需要 Python 3.10+，并安装依赖：

```powershell
pip install -r requirements.txt
python av3a2aac-ac3.pyw
```

源码运行时若未打包，程序会使用 `C:\Users\13568\Downloads\ffmpeg-av3a` 下的 ffmpeg
（含 AV3A 解码器 libarcdav3a）。如需换用其他构建，修改源码顶部
`DEFAULT_FFMPEG_DIR` 或把 `ffmpeg` 子目录放到脚本同级目录即可。

## 打包 EXE

先把带 AV3A 解码器的 ffmpeg 目录准备好（默认 `C:\Users\13568\Downloads\ffmpeg-av3a`，
需含 `ffmpeg.exe` 及其全部依赖 DLL），然后：

```powershell
.\build.ps1


