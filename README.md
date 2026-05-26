# Token Spendie

macOS menu-bar widget ที่ monitor การใช้ token ของ **Claude**, **Codex** และ **Gemini** จาก log ในเครื่อง

![icon](AppIcon.icns)

## Features

- 🟣 **Claude** — Session (5h), Weekly (all models), Weekly · Sonnet — จาก `~/.claude/projects/**/*.jsonl`
- 🟢 **Codex** — Session (5h), Weekly + จำนวน turns — จาก `~/.codex/log/codex-tui.log`
- 🔵 **Gemini** — Daily requests — จาก `~/.gemini/tmp/gemini-cli/`
- 🟢🟡🔴 ไฟสถานะตาม % การใช้งาน + progress bar
- ⏱ เลือก refresh interval ได้ (1 / 2 / 5 / 10 / 15 / 30 / 60 นาที)
- 🚀 Start at login (toggle ได้)
- ⚙️ ปรับ limit ของแต่ละค่ายได้
- ⏻ Quit แล้ว kill process จริง

## Build & Install

```bash
./build_app.sh
```

สร้าง `Token Spendie.app` — ดับเบิลคลิกเปิดได้ หรือลากไปไว้ใน **Applications / Dock / Desktop**
มองหาไอคอน **◈** บน menu bar

> ไฟล์ Python ถูกฝังใน `.app` (self-contained) เพื่อเลี่ยงข้อจำกัด macOS TCC เวลา launch จาก `~/Documents`
> แก้โค้ดแล้วต้องรัน `./build_app.sh` ใหม่ทุกครั้ง

## Run แบบ dev (ไม่ผ่าน bundle)

```bash
./run.sh
```

## ตั้งค่า

- คลิก **⏱ Refresh every** เพื่อเลือกความถี่ — บันทึกอัตโนมัติ
- คลิก **🚀 Start at login** เพื่อ toggle auto-start (สร้าง LaunchAgent ที่ `~/Library/LaunchAgents/com.tokenspendie.agent.plist`)
- คลิก **⚙️ Edit limits…** เพื่อแก้ limit ที่ `~/.config/token_spendie/config.json`
  (แก้แล้วกด **🔄 Refresh now** ไม่ต้อง restart)

## หมายเหตุ

- **ChatGPT (desktop app)** อ่านไม่ได้ — เข้ารหัส local storage ทั้งหมด ดู token ที่ platform.openai.com/usage แทน
- Limit ที่ตั้งไว้เป็นค่าประมาณ ปรับให้ตรงกับ plan ของคุณได้ใน config
