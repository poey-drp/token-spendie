# Token Spendie

macOS menu-bar widget ที่ monitor การใช้ **token** ของ **Claude**, **Codex** และ **Gemini**
โดยอ่านจาก log ในเครื่อง — **ไม่เรียก API ไม่เปลือง token** (0 token ต่อการ refresh)

<p align="center">
  <img src="docs/screenshot.png" alt="Token Spendie menu" width="360">
</p>

---

## Features

- **Claude** — **% จริงจาก `/status`** (Session 5h + Weekly 7d) ดึงสดจาก official `anthropic-ratelimit-unified-*` headers + แสดง spend estimate จาก log
  - ถ้า token หมดอายุ → fallback เป็น cost+token จาก `~/.claude/projects/**/*.jsonl` อัตโนมัติ
- **Codex** — Session (5h) / Weekly + จำนวน turns — จาก `~/.codex/log/codex-tui.log`
- **Gemini** — Daily requests — จาก `~/.gemini/tmp/gemini-cli/`
- **UI โมเดิร์น** — progress bar ไล่สี (เขียว→เหลือง→แดง) โค้งมน, ตัวเลข % สีตามสถานะ,
  section header ไล่ letter-spacing, ปุ่มล่างใช้ SF Symbols — ไม่มี emoji ดอทกลม
- เลือก refresh interval ได้ (1 / 2 / 5 / 10 / 15 / 30 / 60 นาที)
- Start at login (toggle ได้ผ่าน LaunchAgent)
- ปรับ limit ของแต่ละค่ายได้
- Quit แล้ว kill process จริง
- เป็น **menu-bar-only** (ไม่มี Dock icon ขณะรัน)

## Build & Install

```bash
git clone https://github.com/poey-drp/token-spendie.git
cd token-spendie
./build_app.sh
open "Token Spendie.app"
```

`build_app.sh` จะ:
1. ติดตั้ง dependencies (`rumps`, `Pillow`)
2. generate icon (`make_icons.py`)
3. แพ็กเป็น `Token Spendie.app` แบบ self-contained

จากนั้นดับเบิลคลิก หรือลากไปไว้ใน **Applications / Dock / Desktop** แล้วมองหาไอคอน **◈** บน menu bar

> แก้โค้ดแล้วต้องรัน `./build_app.sh` ใหม่ทุกครั้ง
> รันแบบ dev (ไม่ผ่าน bundle): `./run.sh`

## การตั้งค่า

- **Refresh every** — เลือกความถี่ (บันทึกลง config อัตโนมัติ)
- **Start at login** — toggle auto-start (LaunchAgent `~/Library/LaunchAgents/com.tokenspendie.agent.plist`)
- **Edit limits…** — แก้ limit ที่ `~/.config/token_spendie/config.json` (กด Refresh now ไม่ต้อง restart)

## ความแม่นยำของตัวเลข

- **Claude = ตัวเลขจริง (live API)** — ดึง `anthropic-ratelimit-unified-5h/7d-utilization` ซึ่งเป็น
  source เดียวกับ `/status` → ตรงเป๊ะ
  - ใช้ OAuth token ที่ Claude Code เก็บใน **Keychain** (อ่านอย่างเดียว ไม่ refresh เอง เพื่อไม่ให้
    Claude Code ของจริงหลุด login) — poll ทุก 5 นาที (ปรับได้), call จิ๋ว ~$0.01/วัน
  - token หมดอายุ → fallback เป็น **cost estimate จาก log** (pricing calibrate กับ /usage:
    sonnet ตรง, opus cache-read ปรับให้ตรง $) → เปิด Claude Code ครั้งเดียว token จะ fresh
  - ปิด live API ได้ใน config (`claude_use_api: false`) ถ้าไม่อยากให้ยิง API
- **Codex / Gemini** — ประมาณจาก log ในเครื่อง (Codex นับ fresh tokens, Gemini นับ requests)
- **ChatGPT desktop app อ่านไม่ได้** — เข้ารหัส local storage ทั้งหมด ดู token จริงที่ platform.openai.com/usage

## โครงสร้างไฟล์

| ไฟล์ | หน้าที่ |
|------|--------|
| `token_spendie.py` | แอปหลัก (อ่าน log + rumps menu + styling) |
| `build_app.sh` | สร้าง `Token Spendie.app` |
| `make_icons.py` | generate `menubar_icon.png` + `AppIcon.icns` |
| `run.sh` | รันแบบ dev |
| `requirements.txt` | `rumps`, `Pillow` |

## How it works (technical notes)

การแพ็ก rumps app ให้ launch ผ่าน `.app` bundle แล้ว menu-bar icon โผล่จริง เจอกับดัก 4 ข้อ —
`build_app.sh` + `token_spendie.py` แก้ไว้ให้แล้วทั้งหมด:

1. **TCC บล็อก `~/Documents`** — app ที่ launch ผ่าน LaunchServices (`open`) อ่านไฟล์ใน `~/Documents`
   ไม่ได้ (`Operation not permitted`)
   → `build_app.sh` คัดลอก source + icon เข้า `Contents/Resources/` (self-contained) เพราะ app
   เข้าถึง resource ของตัวเองได้เสมอ. (`~/.claude` `~/.codex` `~/.gemini` อยู่ home ไม่โดน TCC)

2. **ต้องใช้ framework / GUI python** — python ที่ไม่ใช่ framework build (เช่น anaconda `bin/python3`)
   ต่อ WindowServer ไม่ได้ → NSStatusItem ไม่โผล่
   → `build_app.sh` ตรวจหา framework python (`python.app/.../python`) อัตโนมัติ

3. **launcher ต้อง _detach_ python ไม่ใช่ `exec`** — ถ้า `exec python` ผ่าน LaunchServices ตัว process
   จะค้างใน "app slot" ของ bundle → มี Dock icon แต่ menu-bar icon ไม่โผล่
   → ใช้ `nohup … & disown` ให้ python register ใหม่เป็น GUI app สดๆ เหมือน launch จาก terminal

4. **ซ่อน Dock icon** — detached python register เป็นตัวมันเอง LSUIElement ใน plist คุมไม่ถึง
   → ตั้ง `NSApplication.setActivationPolicy_(1)` (Accessory) ในโค้ด

> styling helper ทุกตัว (gradient bar / attributed text / SF Symbols) ห่อ try/except
> ถ้า AppKit/PIL ล้มจะ fallback เป็น text ธรรมดาแทน crash

## Requirements

- macOS 11+ (Apple Silicon หรือ Intel)
- Python 3.10+ (แนะนำ framework / GUI python เพื่อให้ menu-bar icon แสดง — `build_app.sh` เลือกให้อัตโนมัติ)

## License

[MIT](LICENSE) © 2026 Poey
