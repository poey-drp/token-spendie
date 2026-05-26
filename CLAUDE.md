# Token Spendie — สถานะโปรเจกต์ & บันทึกที่เรียนรู้

macOS menu-bar widget ที่ monitor token usage ของ Claude / Codex / Gemini จาก log ในเครื่อง
สร้างด้วย Python + `rumps`

---

## ✅ ใช้งานได้แล้ว

- **อ่านข้อมูลครบ 3 ค่าย**
  - Claude — `~/.claude/projects/**/*.jsonl` (field `message.usage` + `timestamp`) → Session 5h / Weekly / Weekly·Sonnet
  - Codex — `~/.codex/log/codex-tui.log` (regex จับ `codex.turn.token_usage.*`) → Session 5h / Weekly + turns
  - Gemini — `~/.gemini/tmp/gemini-cli/logs.json` + `chats/` → Daily request count
- **UI (ปรับใหม่ 2026-05-26)** — โมเดิร์น ไม่มี emoji ดอทกลม:
  - progress bar = **ภาพ PNG ไล่สีจริง** (เขียว→เหลือง→แดง โค้งมน retina) สร้างด้วย PIL cache ที่ `$TMPDIR/token_spendie_bars/` แล้ว `set_icon(..., template=False)`
  - % ใช้ **NSAttributedString** สีตามสถานะ + ชิดขวาด้วย `NSTextTab` (คอลัมน์ตรงขอบ bar)
  - section header = ตัวอักษร bold + kern + สีแบรนด์นุ่ม (CLAUDE ม่วง / CODEX เขียว / GEMINI ฟ้า) ไม่มีวงกลม
  - ปุ่มล่าง = **SF Symbols** (template, monochrome) แทน emoji
  - ทุก styling helper ห่อ try/except → ถ้า AppKit/PIL พังจะ fallback เป็น text ธรรมดา ไม่ crash
- **Refresh interval** เลือกได้ผ่าน submenu (1/2/5/10/15/30/60 นาที) — บันทึกลง config อัตโนมัติ
- **Start at login** — toggle สร้าง/ลบ LaunchAgent `~/Library/LaunchAgents/com.tokenspendie.agent.plist`
  (ทดสอบด้วย `launchctl kickstart` แล้ว launch ได้จริง)
- **Quit** — หยุด timer + `quit_application()` + `SIGTERM` fallback (kill จริง)
- **`.app` bundle** double-click / วาง Dock / Desktop ได้ — `./build_app.sh`
- **Menu-bar icon ◈ โผล่เมื่อ launch ผ่าน bundle** ✅ (แก้ได้แล้ว — ดูด้านล่าง)
- **Verify รอบสุดท้ายผ่านแล้ว** ✅ — launch ผ่าน `.app` bundle ได้ทั้ง ◈ โผล่ + ไม่มี Dock icon
  (type=`UIElement`, log สะอาด, ผู้ใช้ยืนยันด้วยตา 2026-05-26)

---

## 🔑 ปัญหาที่เจอและวิธีแก้ (สำคัญมาก อย่าทำซ้ำ)

### 1. TCC บล็อก `~/Documents`
App ที่ launch ผ่าน LaunchServices (`open`) อ่านไฟล์ใน `~/Documents` ไม่ได้ → `Operation not permitted`
**แก้:** `build_app.sh` คัดลอก `token_spendie.py` + icon เข้าไปใน `Contents/Resources/` (self-contained)
app เข้าถึง resource ของตัวเองได้เสมอ. หมายเหตุ: `~/.claude` `~/.codex` `~/.gemini` อยู่ home ไม่โดน TCC

### 2. Anaconda python ไม่ใช่ framework build → ไม่มี menu-bar icon
`/opt/anaconda3/bin/python3` ต่อ WindowServer ไม่ได้ NSStatusItem เลยไม่โผล่
**แก้:** ใช้ framework GUI python `/opt/anaconda3/python.app/Contents/MacOS/python`
(`build_app.sh` ตรวจหา framework python อัตโนมัติ, ใช้ `bin/python3` แค่ตอน `pip install`)

### 3. ⭐ exec python ผ่าน LaunchServices → icon ไม่โผล่ (ตัวที่ติดนานสุด)
ถึงจะใช้ framework python แล้ว ถ้า launcher `exec python ...` ตัว process จะค้างอยู่ใน
"app slot" ของ bundle ที่ LaunchServices จอง → **มี Dock icon แต่ NSStatusItem ไม่โผล่**
(รัน script ตรงจาก terminal ได้ปกติ — ต่างกันแค่ผ่าน `open` หรือไม่)
**แก้:** launcher ต้อง **detach** python ไม่ใช่ exec:
```bash
nohup "$PY" "$HERE/token_spendie.py" >> "$HOME/.config/token_spendie/agent.log" 2>&1 &
disown
```
python จะ register ใหม่เป็น GUI app สดๆ เหมือน launch จาก terminal → icon โผล่ ✅

### 4. ซ่อน Dock icon (menu-bar-only)
detached python register เป็น `python.app` เอง LSUIElement ใน plist เราคุมไม่ถึง
**แก้:** ตั้ง activation policy ในโค้ด — `NSApplication.sharedApplication().setActivationPolicy_(1)` (Accessory)

---

## 📊 ความแม่นยำของตัวเลข (สำคัญ)

### Claude = LIVE API (วิธีสุดท้าย ✅ แม่นจริง)
- log อย่างเดียวเลียน % ของ /status ไม่ได้ (เพราะ /status คิดจาก context size + weighting
  server-side: fresh token เพิ่ม 23% แต่ official พุ่ง 5 เท่า → ไม่ proportional)
- **ทางออก: ดึง `anthropic-ratelimit-unified-5h/7d-utilization` headers** = source เดียวกับ /status
  - ยิง `POST /v1/messages` (haiku, max_tokens:1) อ่าน response headers — **count_tokens ไม่แนบ headers พวกนี้**
  - auth: อ่าน OAuth token จาก Keychain `security find-generic-password -s "Claude Code-credentials"`
    (field `claudeAiOauth.accessToken` + `expiresAt`)
  - beta header ต้องมี: `anthropic-beta: oauth-2025-04-20`
  - **ห้าม refresh token เอง** — refresh token หมุน single-use จะทำ Claude Code จริงหลุด login
  - poll background thread ทุก `claude_api_poll_minutes` (default 5) → cache → สั่ง `_refresh_data()` ทันที
    (สำคัญ: ถ้าไม่สั่ง re-render UI จะค้างจอ loading จนถึงรอบ refresh ถัดไป)
  - token หมด/อ่านไม่ได้ → fallback log cost
- **bundle context อ่าน Keychain ได้** (ทดสอบแล้ว ไม่เด้ง prompt — binary เดิม)

### Fallback: cost จาก log
- pricing calibrate ตรง /usage (`CLAUDE_PRICING`): sonnet standard, opus cache_read=$0.20/M
  (back out จาก $22.26 ตัวอย่าง /usage) → รวม $23.98 vs จริง $23.95
- token ที่แสดง = total throughput (รวม cache); cost = weighted ตาม pricing

### Codex / Gemini — ทำไมไม่ใช้ API (สำรวจแล้ว 2026-05-26)
- **Gemini ❌** — auth `~/.gemini/oauth_creds.json` (Google OAuth personal). refresh ได้ด้วย
  public gemini-cli client creds (token หมดบ่อยเพราะ CLI ไม่ได้รัน). แต่ `cloudcode-pa.googleapis.com
  /v1internal:loadCodeAssist` คืนแค่ **tier** (`currentTier`/`allowedTiers`/`paidTier`) — **ไม่มี
  usage count/quota/remaining**. tier ผู้ใช้ = "standard-tier / Unlimited" → limit 1000/วันอาจไม่ใช้ด้วยซ้ำ.
  สรุป: Google ไม่เปิด endpoint usage → คง log counting
- **Codex ⚠️** — auth `~/.codex/auth.json` (ChatGPT token + account_id). rate_limits (primary 5h/
  secondary weekly) อยู่ใน ChatGPT backend `chatgpt.com/backend-api/codex/responses` (undocumented,
  SSE, ต้องใส่ chatgpt-account-id/originator headers). probe แล้ว **timeout** → เปราะ ไม่คุ้มทำ
- สรุป: มีแต่ Anthropic ที่คืน usage% ผ่าน header สะอาด → Codex/Gemini คง log estimate
  (Codex fresh tokens = `total - cached_input`, Gemini นับ requests)

## ⏳ ค้าง / ยังไม่เสร็จ

- **ChatGPT desktop app — อ่านไม่ได้** (`~/Library/Application Support/com.openai.chat/.../*.data` เข้ารหัส)
  ทำได้แค่ทำนับจำนวน conversation; token จริงต้องดูที่ platform.openai.com/usage
- **Limit เป็นค่า calibrated** (Claude session 18M / weekly 7.5M / sonnet 4M, Codex weekly 2M, Gemini 1000/day)
  — fresh tokens, ปรับเองได้ใน `~/.config/token_spendie/config.json` (ดูหมวดความแม่นยำด้านบน)
- **Auto-start ทดสอบแบบ kickstart เท่านั้น** ยังไม่ได้ทดสอบ login จริง

---

## ไฟล์

| ไฟล์ | หน้าที่ |
|------|--------|
| `token_spendie.py` | แอปหลัก (data parsing + rumps menu) |
| `build_app.sh` | สร้าง `Token Spendie.app` (เลือก framework python, ฝังไฟล์, detached launcher) |
| `make_icons.py` | สร้าง `menubar_icon.png` + `AppIcon.icns` (PIL) |
| `run.sh` | รันแบบ dev (ไม่ผ่าน bundle) |
| `requirements.txt` | `rumps`, `Pillow` |

## คำสั่ง

```bash
./build_app.sh            # build/rebuild .app (รันใหม่ทุกครั้งหลังแก้ token_spendie.py)
open "Token Spendie.app"  # launch
pkill -f token_spendie.py # kill
```

## Environment

- ใช้ `/opt/anaconda3/python.app/Contents/MacOS/python` (framework) ตอนรัน GUI
- ใช้ `/opt/anaconda3/bin/python3` ตอน `pip install` / สร้าง icon
- macOS 26.x, Apple Silicon (ARM64)
