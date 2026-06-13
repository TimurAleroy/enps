import os
import asyncio
import requests
from datetime import date
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_PROBLEMS_DB_ID = "88be90a6768e4c9da2819565e1a69f62"
ADMIN_CHAT_ID = 188483198
ENPS_SHEETS_ID = "1nKMCWGXsdQ-3KgMeFtPkIlmKlim4Ae6YFT-jEnZnLwY"
CSI_SHEETS_ID = "1SOKanELXstuJ0W75fsWpbmYRibk-mWkHLF5XHz4KHYc"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

processed_rows = set()
bot_app = None

# ─── CSI/NPS ─────────────────────────────────────────

def get_csi_rows():
    url = f"https://docs.google.com/spreadsheets/d/{CSI_SHEETS_ID}/gviz/tq?tqx=out:csv&sheet=Sheet1"
    res = requests.get(url)
    if res.status_code != 200:
        return []
    lines = res.text.strip().split("\n")
    rows = []
    for line in lines[1:]:
        cols = [c.strip().strip('"') for c in line.split(",")]
        if len(cols) >= 7 and cols[0]:
            rows.append(cols)
    return rows

def find_worst_score(cols):
    categories = [(1, "Общее"), (2, "Кальян"), (3, "Напитки"), (4, "Еда"), (5, "Команда")]
    worst_score, worst_cat = 10, "Общее"
    for idx, cat in categories:
        try:
            score = float(cols[idx].replace(",", "."))
            if score < worst_score:
                worst_score, worst_cat = score, cat
        except:
            pass
    return worst_score, worst_cat

def create_notion_problem(cols, worst_score, worst_cat):
    comment = cols[7].strip() if len(cols) > 7 else ""
    visit_date = cols[0].split(" ")[0] if cols[0] else date.today().isoformat()
    try:
        parts = visit_date.split(".")
        if len(parts) == 3:
            visit_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    except:
        visit_date = date.today().isoformat()

    page_data = {
        "parent": {"database_id": NOTION_PROBLEMS_DB_ID},
        "properties": {
            "Проблема": {"title": [{"text": {"content": f"Низкая оценка — {worst_cat} ({worst_score}/10)"}}]},
            "Категория": {"select": {"name": worst_cat}},
            "Оценка гостя": {"number": worst_score},
            "Комментарий гостя": {"rich_text": [{"text": {"content": comment or "Без комментария"}}]},
            "Дата отзыва": {"date": {"start": visit_date}},
            "Статус": {"select": {"name": "Новая"}}
        }
    }
    res = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=page_data)
    return res.status_code == 200

async def check_reviews():
    global bot_app
    if not bot_app:
        return
    rows = get_csi_rows()
    for cols in rows:
        row_id = cols[0]
        if row_id in processed_rows:
            continue
        processed_rows.add(row_id)
        worst_score, worst_cat = find_worst_score(cols)

        if worst_score < 7 and comment:
            comment = cols[7].strip() if len(cols) > 7 else ""
            scores_text = (
                f"😊 Вечер: {cols[1]}/10\n"
                f"🪄 Кальян: {cols[2]}/10\n"
                f"🍹 Напитки: {cols[3]}/10\n"
                f"🍽 Еда: {cols[4]}/10\n"
                f"👨‍💼 Команда: {cols[5]}/10\n"
                f"🎯 NPS: {cols[6]}/10"
            )
            text = f"🚨 *Негативный отзыв гостя!*\n\n{scores_text}\n👎 Проблема: *{worst_cat}* ({worst_score}/10)\n"
            if comment:
                text += f"💬 _{comment}_\n"

            created = create_notion_problem(cols, worst_score, worst_cat)
            text += "\n✅ Задача создана в Notion!" if created else "\n⚠️ Не удалось создать задачу."

            await bot_app.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode="Markdown")

# ─── eNPS ────────────────────────────────────────────

def get_enps_data():
    url = f"https://docs.google.com/spreadsheets/d/{ENPS_SHEETS_ID}/gviz/tq?tqx=out:csv&sheet=enps"
    res = requests.get(url)
    if res.status_code != 200:
        return None
    lines = res.text.strip().split("\n")
    if len(lines) < 2:
        return None

    rows = []
    for line in lines[1:]:
        cols = [c.strip().strip('"') for c in line.split(",")]
        if len(cols) >= 2 and cols[1]:
            rows.append(cols)
    if not rows:
        return None

    this_month = date.today().strftime("%m")
    month_rows = [r for r in rows if r[0].startswith(this_month + ".")]
    use_rows = month_rows if month_rows else rows
    total = len(use_rows)

    promoters = neutrals = critics = 0
    likes, improvements = [], []
    for r in use_rows:
        try:
            score = float(r[1].replace(",", "."))
            if score >= 9: promoters += 1
            elif score >= 7: neutrals += 1
            else: critics += 1
        except:
            pass
        if len(r) > 2 and r[2].strip():
            likes.append(r[2].strip())
        if len(r) > 3 and r[3].strip():
            improvements.append(r[3].strip())

    enps = round(((promoters - critics) / total) * 100) if total > 0 else 0

    prev_month_num = date.today().month - 1
    prev_year = date.today().year
    if prev_month_num == 0:
        prev_month_num = 12
        prev_year -= 1
    prev_month = f"{prev_month_num:02d}"
    prev_rows = [r for r in rows if r[0].startswith(prev_month + ".")]
    prev_enps = None
    if prev_rows:
        pt = len(prev_rows)
        pp = pc = 0
        for r in prev_rows:
            try:
                s = float(r[1].replace(",", "."))
                if s >= 9: pp += 1
                elif s < 7: pc += 1
            except: pass
        prev_enps = round(((pp - pc) / pt) * 100) if pt > 0 else 0

    return {
        "total": total, "promoters": promoters, "neutrals": neutrals,
        "critics": critics, "enps": enps, "prev_enps": prev_enps,
        "likes": likes[-5:], "improvements": improvements[-5:],
        "period": "этот месяц" if month_rows else "всё время"
    }

# ─── КОМАНДЫ ─────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👨‍💼 *Бот администратора*\n\n"
        "🔔 Уведомляю о негативных отзывах каждый час.\n\n"
        "/enps — eNPS сотрудников\n"
        "/problems — открытые проблемы",
        parse_mode="Markdown"
    )

async def enps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Загружаю данные...")
    data = get_enps_data()
    if not data:
        await update.message.reply_text("❌ Нет данных.")
        return

    if data["prev_enps"] is not None:
        diff = data["enps"] - data["prev_enps"]
        trend = f"📈 +{diff}" if diff > 0 else (f"📉 {diff}" if diff < 0 else "➡️ Без изменений")
    else:
        trend = "📊 Нет данных за прошлый месяц"

    rating = "🟢 Отлично" if data["enps"] >= 50 else ("🟡 Хорошо" if data["enps"] >= 20 else ("🟠 Удовлетворительно" if data["enps"] >= 0 else "🔴 Критично"))

    text = (
        f"👨‍💼 *eNPS Сотрудников*\n"
        f"_{data['period']} · {data['total']} ответов_\n\n"
        f"🎯 *eNPS: {data['enps']}* — {rating}\n"
        f"{trend}\n\n"
        f"👍 Промоутеры (9-10): *{data['promoters']}*\n"
        f"😐 Нейтралы (7-8): *{data['neutrals']}*\n"
        f"👎 Критики (0-6): *{data['critics']}*\n"
    )
    if data["likes"]:
        text += "\n✅ *Что нравится:*\n" + "".join(f"  • {l}\n" for l in data["likes"])
    if data["improvements"]:
        text += "\n⚠️ *Что улучшить:*\n" + "".join(f"  • {i}\n" for i in data["improvements"])

    await update.message.reply_text(text, parse_mode="Markdown")

async def problems(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_PROBLEMS_DB_ID}/query",
        headers=NOTION_HEADERS,
        json={
            "filter": {
                "or": [
                    {"property": "Статус", "select": {"equals": "Новая"}},
                    {"property": "Статус", "select": {"equals": "В работе"}}
                ]
            },
            "sorts": [{"property": "Дата отзыва", "direction": "descending"}]
        }
    )
    results = res.json().get("results", [])

    if not results:
        await update.message.reply_text("✅ Открытых проблем нет!")
        return

    text = f"⚠️ *Открытые проблемы ({len(results)}):*\n\n"
    for p in results:
        props = p["properties"]
        category = props["Категория"]["select"]["name"] if props["Категория"]["select"] else "—"
        score = props["Оценка гостя"]["number"] if props["Оценка гостя"]["number"] else "—"
        status = props["Статус"]["select"]["name"] if props["Статус"]["select"] else "—"
        deadline = props["Срок исполнения"]["date"]["start"] if props["Срок исполнения"]["date"] else "не указан"
        responsible = props["Ответственный"]["rich_text"][0]["plain_text"] if props["Ответственный"]["rich_text"] else "не назначен"
        status_icon = "🔴" if status == "Новая" else "🟡"
        text += f"{status_icon} *{category}* — {score}/10\n   👤 {responsible} · 📅 {deadline}\n\n"

    await update.message.reply_text(text, parse_mode="Markdown")

# ─── ЗАПУСК ──────────────────────────────────────────

async def post_init(application):
    global bot_app
    bot_app = application
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_reviews, "interval", hours=1, id="check_reviews")
    scheduler.start()
    # Первая проверка сразу при старте
    await check_reviews()

app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("enps", enps))
app.add_handler(CommandHandler("problems", problems))
app.run_polling()
