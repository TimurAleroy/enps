import os
import requests
from datetime import date
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
SHEETS_ID = "1nKMCWGXsdQ-3KgMeFtPkIlmKlim4Ae6YFT-jEnZnLwY"

def get_enps_data():
    # Читаем лист enps
    url = f"https://docs.google.com/spreadsheets/d/{SHEETS_ID}/gviz/tq?tqx=out:csv&sheet=enps"
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

    this_month = date.today().strftime("%m.%Y")
    month_rows = [r for r in rows if r[0].startswith(this_month[:2])]
    use_rows = month_rows if month_rows else rows
    total = len(use_rows)

    promoters = neutrals = critics = 0
    likes = []
    improvements = []

    for r in use_rows:
        try:
            score = float(r[1].replace(",", "."))
            if score >= 9:
                promoters += 1
            elif score >= 7:
                neutrals += 1
            else:
                critics += 1
        except:
            pass

        if len(r) > 2 and r[2].strip():
            likes.append(r[2].strip())
        if len(r) > 3 and r[3].strip():
            improvements.append(r[3].strip())

    enps = round(((promoters - critics) / total) * 100) if total > 0 else 0

    # Динамика — сравниваем с прошлым месяцем
    prev_month_num = date.today().month - 1
    prev_year = date.today().year
    if prev_month_num == 0:
        prev_month_num = 12
        prev_year -= 1
    prev_month = f"{prev_month_num:02d}.{prev_year}"
    prev_rows = [r for r in rows if r[0].startswith(prev_month[:2])]

    prev_enps = None
    if prev_rows:
        prev_total = len(prev_rows)
        prev_p = prev_n = prev_c = 0
        for r in prev_rows:
            try:
                s = float(r[1].replace(",", "."))
                if s >= 9: prev_p += 1
                elif s >= 7: prev_n += 1
                else: prev_c += 1
            except: pass
        prev_enps = round(((prev_p - prev_c) / prev_total) * 100) if prev_total > 0 else 0

    return {
        "total": total,
        "promoters": promoters,
        "neutrals": neutrals,
        "critics": critics,
        "enps": enps,
        "prev_enps": prev_enps,
        "likes": likes[-5:],
        "improvements": improvements[-5:],
        "period": "этот месяц" if month_rows else "всё время"
    }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот для отслеживания eNPS сотрудников.\n\n"
        "/enps — показать текущий eNPS\n"
        "/help — помощь"
    )

async def enps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Загружаю данные...")

    data = get_enps_data()
    if not data:
        await update.message.reply_text("❌ Не удалось загрузить данные. Проверьте доступ к таблице.")
        return

    # Динамика
    if data["prev_enps"] is not None:
        diff = data["enps"] - data["prev_enps"]
        if diff > 0:
            trend = f"📈 +{diff} к прошлому месяцу"
        elif diff < 0:
            trend = f"📉 {diff} к прошлому месяцу"
        else:
            trend = "➡️ Без изменений"
    else:
        trend = "📊 Нет данных за прошлый месяц"

    # Оценка eNPS
    if data["enps"] >= 50:
        rating = "🟢 Отлично"
    elif data["enps"] >= 20:
        rating = "🟡 Хорошо"
    elif data["enps"] >= 0:
        rating = "🟠 Удовлетворительно"
    else:
        rating = "🔴 Критично"

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
        text += f"\n✅ *Что нравится:*\n"
        for l in data["likes"]:
            text += f"  • {l}\n"

    if data["improvements"]:
        text += f"\n⚠️ *Что улучшить:*\n"
        for i in data["improvements"]:
            text += f"  • {i}\n"

    await update.message.reply_text(text, parse_mode="Markdown")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *eNPS бот — помощь*\n\n"
        "/enps — текущий eNPS с динамикой и комментариями\n\n"
        "Данные берутся из Google Forms → Google Sheets автоматически.",
        parse_mode="Markdown"
    )

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("enps", enps))
app.add_handler(CommandHandler("help", help_cmd))
app.run_polling()
