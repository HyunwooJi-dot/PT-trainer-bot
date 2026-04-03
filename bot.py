"""
PT 트레이너 텔레그램 봇 v2
────────────────────────────────
[변경된 흐름]
- 회원: 이름 입력 → 오늘 운동 수신 → 수업완료 버튼 (기록만)
- 트레이너: 수업 완료 알림 수신 or /수업완료 이름
  → AI가 숙제 생성 → 트레이너에게 전송
  → 트레이너가 직접 회원에게 전달
- 구글 캘린더: 수업 이벤트 종료 감지 → 트레이너에게 자동 알림
"""

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from dotenv import load_dotenv
from datetime import datetime
import sheets
import ai_homework

load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TRAINER_CHAT_ID = os.getenv("TRAINER_CHAT_ID")


# ─────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────

def is_trainer(update: Update) -> bool:
    return str(update.message.chat_id) == str(TRAINER_CHAT_ID)


def get_today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ─────────────────────────────────────────────
# 공통
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    if chat_id == str(TRAINER_CHAT_ID):
        await update.message.reply_text(
            "👋 *PT 트레이너 봇* 시작!\n\n"
            "*트레이너 명령어:*\n"
            "• `/register 이름 수업요일 특이사항` — 회원 등록\n"
            "• `/members` — 전체 회원 보기\n"
            "• `/workout 이름 날짜 운동내용` — 운동 등록\n"
            "• `/notes 이름 내용` — 특이사항 업데이트\n"
            "• `/done 이름` — 수업 완료 처리 + 숙제 생성\n"
            "• `/homework 이름 추가요청(선택)` — 숙제만 생성\n\n"
            "📅 구글 캘린더 연동 시 수업 종료 자동 감지!",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "안녕하세요! 💪 *PT 봇*에 오신 걸 환영해요!\n\n"
            "이름을 입력하면 오늘의 운동을 알려드릴게요.\n"
            "예시: `홍길동`",
            parse_mode="Markdown"
        )


# ─────────────────────────────────────────────
# 회원용
# ─────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """회원이 이름을 입력하면 오늘의 운동 전송"""
    text = update.message.text.strip()
    chat_id = str(update.message.chat_id)
    today = get_today()

    # 트레이너 채팅 일반 메시지 → 안내
    if chat_id == str(TRAINER_CHAT_ID):
        await update.message.reply_text(
            "명령어가 필요하면 /start 를 눌러주세요."
        )
        return

    # 회원 조회
    member = sheets.get_member_by_name(text)
    if not member:
        await update.message.reply_text(
            f"'{text}'으로 등록된 회원을 찾을 수 없어요.\n"
            "이름을 정확히 입력하거나 트레이너에게 등록을 요청해주세요! 😊"
        )
        return

    # chat_id 자동 등록
    if not member.get("chat_id"):
        sheets.update_member_chat_id(text, chat_id)

    # 오늘 운동 조회
    workout = sheets.get_workout(text, today)
    sheets.log_activity(text, chat_id, "check_in", today)

    if not workout:
        await update.message.reply_text(
            f"안녕하세요 *{text}*님! 💪\n\n"
            f"오늘({today}) 등록된 운동이 아직 없어요.\n"
            "트레이너에게 문의해주세요!",
            parse_mode="Markdown"
        )
        return

    keyboard = [[InlineKeyboardButton("✅ 수업 완료!", callback_data=f"done_{text}")]]
    await update.message.reply_text(
        f"안녕하세요 *{text}*님! 오늘도 화이팅! 💪\n\n"
        f"📋 *오늘의 운동* ({today})\n\n"
        f"{workout}\n\n"
        "수업이 끝나면 아래 버튼을 눌러주세요 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_workout_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """회원이 수업 완료 버튼 클릭 → 기록만, 트레이너에게 알림"""
    query = update.callback_query
    await query.answer()

    name = query.data.replace("done_", "")
    chat_id = str(query.message.chat_id)
    today = get_today()

    sheets.mark_workout_done(name, today)
    sheets.log_activity(name, chat_id, "workout_done", today)

    await query.edit_message_text(
        f"✅ *{name}*님 수업 완료!\n\n"
        "정말 수고하셨어요! 🎉\n"
        "트레이너가 곧 숙제를 보내드릴 거예요.",
        parse_mode="Markdown"
    )

    # 트레이너에게 알림 (숙제 생성 버튼 포함)
    if TRAINER_CHAT_ID:
        keyboard = [[InlineKeyboardButton(
            f"📝 {name}님 숙제 생성하기",
            callback_data=f"gen_{name}_"
        )]]
        await context.bot.send_message(
            chat_id=TRAINER_CHAT_ID,
            text=f"🔔 *{name}*님이 수업을 완료했습니다!\n\n"
                 f"아래 버튼으로 숙제를 생성하거나\n"
                 f"`/수업완료 {name}` 을 입력하세요.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# ─────────────────────────────────────────────
# 트레이너용 명령어
# ─────────────────────────────────────────────

async def register_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/회원등록 이름 수업요일 특이사항"""
    if not is_trainer(update):
        return
    if not context.args:
        await update.message.reply_text(
            "사용법: `/회원등록 이름 수업요일 특이사항`\n"
            "예: `/회원등록 홍길동 월수금 왼쪽무릎통증`",
            parse_mode="Markdown"
        )
        return
    name = context.args[0]
    schedule = context.args[1] if len(context.args) > 1 else ""
    notes = " ".join(context.args[2:]) if len(context.args) > 2 else ""

    if sheets.get_member_by_name(name):
        await update.message.reply_text(f"⚠️ '{name}'님은 이미 등록되어 있어요.")
        return

    sheets.register_member(name, schedule, notes)
    await update.message.reply_text(
        f"✅ *{name}*님 등록 완료!\n수업: {schedule or '미입력'} | 특이사항: {notes or '없음'}",
        parse_mode="Markdown"
    )


async def set_workout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/운동등록 이름 날짜 운동내용"""
    if not is_trainer(update):
        return
    if len(context.args) < 3:
        await update.message.reply_text(
            "사용법: `/운동등록 이름 날짜 운동내용`\n"
            "예: `/운동등록 홍길동 2024-03-15 스쿼트 3x15, 런지 3x12`",
            parse_mode="Markdown"
        )
        return
    name, date = context.args[0], context.args[1]
    workout = " ".join(context.args[2:])
    sheets.save_workout(name, date, workout)
    await update.message.reply_text(
        f"✅ *{name}*님 {date} 운동 등록 완료!\n`{workout}`",
        parse_mode="Markdown"
    )


async def update_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/특이사항 이름 내용"""
    if not is_trainer(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("사용법: `/특이사항 이름 내용`", parse_mode="Markdown")
        return
    name = context.args[0]
    notes = " ".join(context.args[1:])
    sheets.update_member_notes(name, notes)
    await update.message.reply_text(f"✅ *{name}*님 특이사항 업데이트!\n`{notes}`", parse_mode="Markdown")


async def list_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/회원목록"""
    if not is_trainer(update):
        return
    members = sheets.get_all_members()
    if not members:
        await update.message.reply_text("등록된 회원이 없습니다.")
        return
    lines = ["📋 *전체 회원 목록*\n"]
    for m in members:
        icon = "🟢" if m.get("chat_id") else "🔴"
        name = m.get("이름", "-")
        schedule = m.get("수업요일", "-") or "-"
        notes = (m.get("특이사항", "") or "")[:20]
        lines.append(f"{icon} *{name}* | {schedule} | {notes}")
    lines.append("\n🟢 봇 연결됨  🔴 미연결")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def class_done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/수업완료 이름 [특이사항] — 수업 완료 처리 + 숙제 생성"""
    if not is_trainer(update):
        return
    if not context.args:
        await update.message.reply_text("사용법: `/수업완료 이름 추가요청(선택)`", parse_mode="Markdown")
        return

    name = context.args[0]
    special_note = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    today = get_today()

    member = sheets.get_member_by_name(name)
    if not member:
        await update.message.reply_text(f"⚠️ '{name}'님을 찾을 수 없어요.")
        return

    # 수업 완료 기록
    sheets.mark_workout_done(name, today)

    msg = await update.message.reply_text(f"🤖 *{name}*님 숙제 생성 중...", parse_mode="Markdown")
    homework = await _generate_and_preview(context, name, special_note, msg)


async def generate_homework_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/숙제생성 이름 [추가요청] — 수업 완료 처리 없이 숙제만 생성"""
    if not is_trainer(update):
        return
    if not context.args:
        await update.message.reply_text("사용법: `/숙제생성 이름 추가요청(선택)`", parse_mode="Markdown")
        return

    name = context.args[0]
    special_note = " ".join(context.args[1:]) if len(context.args) > 1 else ""

    member = sheets.get_member_by_name(name)
    if not member:
        await update.message.reply_text(f"⚠️ '{name}'님을 찾을 수 없어요.")
        return

    msg = await update.message.reply_text(f"🤖 *{name}*님 숙제 생성 중...", parse_mode="Markdown")
    await _generate_and_preview(context, name, special_note, msg)


# ─────────────────────────────────────────────
# 숙제 생성 공통 함수
# ─────────────────────────────────────────────

async def _generate_and_preview(context, name: str, special_note: str, msg):
    """AI 숙제 생성 후 트레이너에게 미리보기 전송"""
    today = get_today()
    member = sheets.get_member_by_name(name)
    member_notes = (member.get("특이사항", "") or "") if member else ""
    today_workout = sheets.get_workout(name, today)

    homework = await ai_homework.generate_homework(name, today_workout, member_notes, special_note)
    context.bot_data[f"hw_{name}"] = {"homework": homework, "special_note": special_note}

    keyboard = [[
        InlineKeyboardButton("🔄 다시 생성", callback_data=f"regen_{name}_{special_note}"),
    ]]

    # 트레이너에게 전송할 메시지 (복사해서 회원에게 보낼 수 있게 구분선 포함)
    preview_text = (
        f"📋 *{name}*님 숙제 — 트레이너 확인용\n\n"
        f"{homework}\n\n"
        f"─────────────────\n"
        f"✂️ 위 내용을 복사해서 *{name}*님에게 직접 보내주세요!\n"
        f"또는 다시 생성할 수 있어요. 👇"
    )
    await msg.edit_text(preview_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    # 시트에 저장
    sheets.save_homework(name, today, homework)
    return homework


# ─────────────────────────────────────────────
# 콜백 핸들러
# ─────────────────────────────────────────────

async def handle_gen_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """수업 완료 알림의 '숙제 생성하기' 버튼"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_", 2)
    name = parts[1]
    special_note = parts[2] if len(parts) > 2 else ""

    member = sheets.get_member_by_name(name)
    if not member:
        await query.edit_message_text("⚠️ 회원 정보를 찾을 수 없어요.")
        return

    msg = await query.edit_message_text(f"🤖 *{name}*님 숙제 생성 중...", parse_mode="Markdown")
    await _generate_and_preview(context, name, special_note, msg)


async def handle_regen_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'다시 생성' 버튼"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_", 2)
    name = parts[1]
    special_note = parts[2] if len(parts) > 2 else ""

    member = sheets.get_member_by_name(name)
    if not member:
        await query.edit_message_text("⚠️ 회원 정보를 찾을 수 없어요.")
        return

    msg = await query.edit_message_text(f"🔄 *{name}*님 숙제 다시 생성 중...", parse_mode="Markdown")
    await _generate_and_preview(context, name, special_note, msg)


# ─────────────────────────────────────────────
# 구글 캘린더 연동 (백그라운드 잡)
# ─────────────────────────────────────────────

async def check_calendar_job(context: ContextTypes.DEFAULT_TYPE):
    """
    매 5분마다 실행 — 방금 종료된 수업 이벤트 감지
    이벤트 제목에 회원 이름이 포함되어 있어야 함
    예: 'PT 홍길동', '홍길동 수업', '홍길동 PT'
    """
    try:
        import calendar_check
        ended_classes = calendar_check.get_recently_ended_classes()

        if not ended_classes:
            return

        members = sheets.get_all_members()
        member_names = [m.get("이름", "") for m in members]

        for event in ended_classes:
            event_title = event.get("title", "")
            matched_member = None

            # 이벤트 제목에서 회원 이름 찾기
            for mname in member_names:
                if mname and mname in event_title:
                    matched_member = mname
                    break

            if not matched_member:
                continue

            # 이미 처리된 이벤트인지 확인
            event_id = event.get("id", "")
            if context.bot_data.get(f"cal_done_{event_id}"):
                continue

            context.bot_data[f"cal_done_{event_id}"] = True

            # 트레이너에게 알림
            if TRAINER_CHAT_ID:
                keyboard = [[InlineKeyboardButton(
                    f"📝 {matched_member}님 숙제 생성",
                    callback_data=f"gen_{matched_member}_캘린더자동감지"
                )]]
                await context.bot.send_message(
                    chat_id=TRAINER_CHAT_ID,
                    text=f"📅 *캘린더 알림*\n\n"
                         f"*{matched_member}*님 수업이 방금 종료됐어요!\n"
                         f"이벤트: {event_title}\n\n"
                         f"숙제를 생성하시겠어요?",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

    except ImportError:
        pass  # calendar_check 모듈 없으면 무시
    except Exception as e:
        logger.error(f"[캘린더 체크 오류] {e}")


# ─────────────────────────────────────────────
# 앱 실행
# ─────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN 환경변수가 설정되지 않았습니다.")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # 핸들러 등록
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register_member))
    app.add_handler(CommandHandler("members", list_members))
    app.add_handler(CommandHandler("workout", set_workout))
    app.add_handler(CommandHandler("notes", update_notes))
    app.add_handler(CommandHandler("done", class_done_command))
    app.add_handler(CommandHandler("homework", generate_homework_command))

    # 콜백
    app.add_handler(CallbackQueryHandler(handle_workout_done, pattern="^done_"))
    app.add_handler(CallbackQueryHandler(handle_gen_callback, pattern="^gen_"))
    app.add_handler(CallbackQueryHandler(handle_regen_callback, pattern="^regen_"))

    # 일반 메시지 (회원 이름 입력)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 캘린더 체크 잡 (5분마다)
    app.job_queue.run_repeating(check_calendar_job, interval=300, first=60)

    logger.info("🤖 PT 봇 v2 시작!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
