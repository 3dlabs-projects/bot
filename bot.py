from flask import Flask
import threading
from threading import Thread
import time
import requests
import traceback
import html
import os
import json
import fitz  # PyMuPDF
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
import logging
import datetime

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 🔐 Bot configuration
OWNER_ID = 6694915001
BOT_TOKEN = os.getenv('BOT_TOKEN', '7910184229:AAFAVUchZ4NwgWpqFYNtZHEL6Da14FtFkxY')

# Conversation states
FULL_NAME, QUALIFICATION, EXPERIENCE, PHONE_NUMBER = range(4)
UPLOAD_QUESTION, UPLOAD_OPTION_A, UPLOAD_OPTION_B, UPLOAD_OPTION_C, UPLOAD_OPTION_D, UPLOAD_CORRECT_ANSWER = range(6)
ANSWER_Q1, ANSWER_Q2, ANSWER_Q3, ANSWER_Q4, ANSWER_Q5 = range(10, 15)

# Global stores
user_progress = {}
authenticated_users = set()
user_data = {}
pending_approvals = {}
question_data = {}

def load_user_progress():
    global user_progress
    if os.path.exists("user_data.json"):
        try:
            with open("user_data.json", "r", encoding="utf-8") as f:
                user_progress = json.load(f)
        except Exception as e:
            logger.error(f"Error loading user progress: {e}")

def load_users():
    if os.path.exists("users.json"):
        try:
            with open("users.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading users: {e}")
    return {}

def save_user_progress():
    try:
        with open("user_data.json", "w", encoding="utf-8") as f:
            json.dump(user_progress, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving user progress: {e}")

def save_users(users):
    try:
        with open("users.json", "w", encoding="utf-8") as f:
            json.dump(users, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving users: {e}")

def load_questions(course_name):
    course_dir = os.path.join("courses", course_name)
    questions_path = os.path.join(course_dir, "questions.json")
    if os.path.exists(questions_path):
        try:
            with open(questions_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading questions: {e}")
    return {"questions": []}

def save_questions(course_name, questions):
    course_dir = os.path.join("courses", course_name)
    os.makedirs(course_dir, exist_ok=True)
    try:
        with open(os.path.join(course_dir, "questions.json"), "w", encoding="utf-8") as f:
            json.dump(questions, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving questions: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"User {update.effective_user.id} started bot")
    await update.message.reply_text(
        "👋 Welcome to the Learning Bot!\n\n"
        "If you're new, please register with /register\n"
        "Existing users can login with /login <username> <phone_number>"
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    users = load_users()
    
    if user_id in users:
        await update.message.reply_text("ℹ️ You are already registered. You can login with /login")
        return ConversationHandler.END
    
    await update.message.reply_text("📝 Let's register you!\n\nPlease enter your Full Name:")
    return FULL_NAME

async def full_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    user_data[user_id] = {"full_name": update.message.text}
    await update.message.reply_text("🎓 What is your highest qualification?")
    return QUALIFICATION

async def qualification_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    user_data[user_id]["qualification"] = update.message.text
    await update.message.reply_text("💼 Do you have work experience? ('Fresher' or 'years of experience in any specific field ')")
    return EXPERIENCE

async def experience_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    user_data[user_id]["experience"] = update.message.text
    await update.message.reply_text("📱 Please share your phone number:")
    return PHONE_NUMBER

async def phone_number_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    phone_number = update.message.text
    
    if not phone_number.isdigit() or len(phone_number) < 10:
        await update.message.reply_text("⚠️ Please enter a valid phone number.")
        return PHONE_NUMBER
    
    user_data[user_id]["phone"] = phone_number
    full_name = user_data[user_id]["full_name"]
    username = (full_name.split()[0] + phone_number[-4:]).lower()
    
    users = load_users()
    users[user_id] = {
        "username": username,
        "phone": phone_number,
        "full_name": full_name,
        "qualification": user_data[user_id]["qualification"],
        "experience": user_data[user_id]["experience"]
    }
    save_users(users)
    del user_data[user_id]

    await update.message.reply_text(
        f"🎉 Registration successful!\n\n"
        f"🔑 Username: {username}\n"
        f"Phone: {phone_number}\n"
        f"Use /login {username} {phone_number} to login."
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id in user_data:
        del user_data[user_id]
    if user_id in question_data:
        del question_data[user_id]
    if user_id in user_progress and "quiz_answers" in user_progress[user_id]:
        del user_progress[user_id]["quiz_answers"]
        del user_progress[user_id]["current_question_index"]
        save_user_progress()
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage: /login <username> <phone_number>")
        return

    username = context.args[0]
    phone = context.args[1]
    user_id = str(update.message.from_user.id)

    users = load_users()
    if user_id in users and users[user_id]["username"] == username and users[user_id]["phone"] == phone:
        authenticated_users.add(user_id)
        await update.message.reply_text(f"✅ Login successful, {users[user_id]['full_name']}! Use /courses to view available courses.")
    else:
        await update.message.reply_text("❌ Invalid username or phone number.")

async def list_courses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in authenticated_users:
        await update.message.reply_text("🔐 Please login first using /login")
        return

    if not os.path.exists("courses"):
        await update.message.reply_text("No courses found.")
        return

    courses = os.listdir("courses")
    if courses:
        await update.message.reply_text("📚 Available courses:\n" + "\n".join(f"- {c}" for c in courses))
    else:
        await update.message.reply_text("No courses uploaded yet.")

async def start_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in authenticated_users:
        await update.message.reply_text("🔐 Please login first using /login")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: /start_course <course_name>")
        return

    course_name = " ".join(context.args)
    course_path = os.path.join("courses", course_name)

    if not os.path.exists(course_path):
        await update.message.reply_text("❌ Course not found.")
        return

    if user_id not in user_progress:
        user_progress[user_id] = {}

    if ("approved_courses" in user_progress[user_id] and 
        course_name in user_progress[user_id]["approved_courses"]):
        user_progress[user_id]["current_course"] = course_name
        user_progress[user_id]["slide_index"] = -1
        user_progress[user_id]["current_slide_group"] = 0
        save_user_progress()
        await update.message.reply_text(f"✅ Starting course: {course_name}\nUse /next to begin.")
        return

    pending_approvals[user_id] = course_name
    user_progress[user_id]["pending_course"] = course_name
    save_user_progress()

    await update.message.reply_text("📩 Request sent to the course admin. Please wait for approval.")
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"👤 User {update.message.from_user.full_name} (ID: {user_id}) requested access to course: {course_name}\n"
             f"Use /approve {user_id} to approve or /reject {user_id} to deny."
    )

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != OWNER_ID:
        await update.message.reply_text("⛔ You're not authorized to approve requests.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /approve <user_id>")
        return

    user_id = context.args[0]
    if user_id not in user_progress or "pending_course" not in user_progress[user_id]:
        await update.message.reply_text("⚠️ No pending course request found for this user.")
        return

    course = user_progress[user_id].pop("pending_course")
    if "approved_courses" not in user_progress[user_id]:
        user_progress[user_id]["approved_courses"] = []
    if course not in user_progress[user_id]["approved_courses"]:
        user_progress[user_id]["approved_courses"].append(course)

    user_progress[user_id]["current_course"] = course
    user_progress[user_id]["slide_index"] = -1
    user_progress[user_id]["current_slide_group"] = 0
    save_user_progress()

    await update.message.reply_text(f"✅ Approved access to '{course}' for user {user_id}.")
    await context.bot.send_message(
        chat_id=int(user_id),
        text=f"✅ Your request to access course '{course}' has been approved!\nUse /next to begin."
    )

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != OWNER_ID:
        await update.message.reply_text("🚫 Only the bot owner can reject requests.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: /reject <user_id>")
        return

    user_id = context.args[0]
    if user_id not in pending_approvals:
        await update.message.reply_text("❌ No pending request from this user.")
        return

    course_name = pending_approvals.pop(user_id)
    await context.bot.send_message(
        chat_id=int(user_id),
        text=f"❌ Your request to access course '{course_name}' has been denied by the admin."
    )
    await update.message.reply_text(f"❌ Rejected access to '{course_name}' for user {user_id}.")

async def next_slide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in authenticated_users:
        await update.message.reply_text("🔐 Please login first using /login")
        return

    if (user_id not in user_progress or 
        "current_course" not in user_progress[user_id] or
        "slide_index" not in user_progress[user_id]):
        await update.message.reply_text("⚠️ You're not in a course session. Use /start_course <name> first.")
        return

    course_name = user_progress[user_id]["current_course"]
    course_path = os.path.join("courses", course_name)
    slides_path = os.path.join(course_path, "slides.json")
    questions = load_questions(course_name)

    if not os.path.exists(slides_path):
        await update.message.reply_text("❌ Course data not found. Please contact admin.")
        return

    try:
        with open(slides_path, "r", encoding="utf-8") as f:
            course_data = json.load(f)
    except Exception as e:
        await update.message.reply_text(f"❌ Error loading course: {str(e)}")
        return

    user_progress[user_id]["slide_index"] += 1
    current_index = user_progress[user_id]["slide_index"]
    current_slide_group = (current_index // 5)
    user_progress[user_id]["current_slide_group"] = current_slide_group
    save_user_progress()

    if current_index >= len(course_data["slides"]):
        await update.message.reply_text("🎉 You've completed this course!")
        del user_progress[user_id]["current_course"]
        del user_progress[user_id]["slide_index"]
        del user_progress[user_id]["current_slide_group"]
        if "quiz_answers" in user_progress[user_id]:
            del user_progress[user_id]["quiz_answers"]
        if "current_question_index" in user_progress[user_id]:
            del user_progress[user_id]["current_question_index"]
        save_user_progress()
        return

    if (current_index + 1) % 5 == 0 and questions["questions"]:
        start_question_index = current_slide_group * 5
        end_question_index = start_question_index + 5
        if len(questions["questions"]) < end_question_index:
            await update.message.reply_text("⚠️ Not enough questions available for this quiz. Contact admin.")
            return
        user_progress[user_id]["quiz_answers"] = []
        user_progress[user_id]["current_question_index"] = 0
        user_progress[user_id]["start_question_index"] = start_question_index
        save_user_progress()
        await send_question(update, context, course_name, questions["questions"][start_question_index])
        return ANSWER_Q1

    save_user_progress()
    await send_slide(update, course_data["slides"][current_index], course_name)

async def send_slide(update: Update, slide: dict, course_name: str):
    try:
        def clean_markdown(text):
            if not text:
                return ""
            for char in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
                text = text.replace(char, f'\\{char}')
            return text

        page_content = clean_markdown(slide.get('page_content', 'Slide'))
        slide_text = clean_markdown(slide.get('text', ''))
        
        max_length = 4000
        if len(slide_text) > max_length:
            parts = [slide_text[i:i+max_length] for i in range(0, len(slide_text), max_length)]
            await update.message.reply_text(
                f"📄 *{page_content}* (Part 1/{len(parts)})",
                parse_mode=ParseMode.MARKDOWN
            )
            for i, part in enumerate(parts[1:], 2):
                await update.message.reply_text(
                    f"📄 *{page_content}* (Part {i}/{len(parts)})\n\n{part}",
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            await update.message.reply_text(
                f"📄 *{page_content}*\n\n{slide_text}",
                parse_mode=ParseMode.MARKDOWN
            )

        for image_file in slide.get('images', []):
            image_path = os.path.join("courses", course_name, image_file)
            if os.path.exists(image_path):
                try:
                    await update.message.reply_photo(photo=open(image_path, "rb"))
                except Exception as e:
                    await update.message.reply_text(f"⚠️ Error sending image: {str(e)}")
            else:
                await update.message.reply_text(f"⚠️ Image {image_file} not found.")
    except Exception as e:
        logger.error(f"Error sending slide: {e}")
        await update.message.reply_text(
            "📄 Here's the slide content (formatting simplified due to error):\n\n" + 
            slide.get('text', 'No content available')
        )

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE, course_name: str, question: dict):
    response = f"❓ {question['question']}\n"
    response += f"A) {question['options']['A']}\n"
    response += f"B) {question['options']['B']}\n"
    response += f"C) {question['options']['C']}\n"
    response += f"D) {question['options']['D']}\n"
    response += "Please reply with the correct option (A, B, C, or D)."
    await update.message.reply_text(response)

async def answer_q1_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_answer(update, context, 0, ANSWER_Q2)

async def answer_q2_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_answer(update, context, 1, ANSWER_Q3)

async def answer_q3_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_answer(update, context, 2, ANSWER_Q4)

async def answer_q4_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_answer(update, context, 3, ANSWER_Q5)

async def answer_q5_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_answer(update, context, 4, None)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question_index: int, next_state):
    user_id = str(update.message.from_user.id)
    answer = update.message.text.upper()

    if answer not in ['A', 'B', 'C', 'D']:
        await update.message.reply_text("⚠️ Invalid answer. Please enter A, B, C, or D:")
        return question_index + 10

    course_name = user_progress[user_id]["current_course"]
    questions = load_questions(course_name)
    start_question_index = user_progress[user_id]["start_question_index"]

    user_progress[user_id]["quiz_answers"].append(answer)
    user_progress[user_id]["current_question_index"] = question_index + 1
    save_user_progress()

    if question_index == 4:
        correct = True
        for i, ans in enumerate(user_progress[user_id]["quiz_answers"]):
            if ans != questions["questions"][start_question_index + i]["correct_answer"]:
                correct = False
                break
        
        if correct:
            await update.message.reply_text("🎉 All answers correct! Use /next to continue with the next slide.")
            del user_progress[user_id]["quiz_answers"]
            del user_progress[user_id]["current_question_index"]
            del user_progress[user_id]["start_question_index"]
            save_user_progress()
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ Some answers were incorrect. Let's try the quiz again.")
            user_progress[user_id]["quiz_answers"] = []
            user_progress[user_id]["current_question_index"] = 0
            save_user_progress()
            await send_question(update, context, course_name, questions["questions"][start_question_index])
            return ANSWER_Q1

    await send_question(update, context, course_name, questions["questions"][start_question_index + question_index + 1])
    return next_state

async def handle_pdf_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != OWNER_ID:
        await update.message.reply_text("🚫 You are not authorized to upload PDFs.")
        return

    document = update.message.document
    if not document.file_name.endswith('.pdf'):
        await update.message.reply_text("⚠️ Please upload a valid PDF file.")
        return

    os.makedirs("temp", exist_ok=True)
    file_path = f"temp/{document.file_name}"
    file = await context.bot.get_file(document.file_id)
    await file.download_to_drive(file_path)
    await update.message.reply_text("📥 PDF received. Processing...")

    course_name = os.path.splitext(document.file_name)[0]
    course_dir = os.path.join("courses", course_name)
    os.makedirs(course_dir, exist_ok=True)

    slides = []
    try:
        pdf_reader = fitz.open(file_path)
        for page_num in range(len(pdf_reader)):
            page = pdf_reader[page_num]
            text = page.get_text("text")

            images = []
            image_list = page.get_images(full=True)
            for img_index, img in enumerate(image_list):
                xref = img[0]
                base_image = pdf_reader.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                image_filename = f"slide_{page_num+1}_img_{img_index+1}.{image_ext}"

                image_path = os.path.join(course_dir, image_filename)
                with open(image_path, "wb") as img_file:
                    img_file.write(image_bytes)
                
                images.append(image_filename)

            slides.append({
                "slide_number": page_num + 1,
                "page_content": f"Slide {page_num + 1}",
                "text": text.strip(),
                "images": images
            })
        pdf_reader.close()
    except Exception as e:
        logger.error(f"Error processing PDF: {e}")
        await update.message.reply_text(f"⚠️ Error processing PDF: {str(e)}")
        return

    course_json = {
        "course_name": course_name,
        "total_slides": len(slides),
        "slides": slides
    }

    try:
        with open(os.path.join(course_dir, "slides.json"), "w", encoding="utf-8") as f:
            json.dump(course_json, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving slides: {e}")
        await update.message.reply_text(f"⚠️ Error saving course data: {str(e)}")
        return

    await update.message.reply_text(f"✅ PDF processed successfully! Course '{course_name}' created.")

async def start_question_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != OWNER_ID:
        await update.message.reply_text("🚫 You are not authorized to upload questions.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: /upload_question <course_name>")
        return

    course_name = " ".join(context.args)
    course_dir = os.path.join("courses", course_name)
    
    if not os.path.exists(course_dir):
        await update.message.reply_text(f"❌ Course '{course_name}' not found.")
        return

    question_data[str(update.message.from_user.id)] = {"course_name": course_name}
    await update.message.reply_text(f"📝 Please send the question for course '{course_name}':")
    return UPLOAD_QUESTION

async def question_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in question_data:
        return ConversationHandler.END

    question_data[user_id]["question"] = update.message.text
    await update.message.reply_text("📝 Please send Option A:")
    return UPLOAD_OPTION_A

async def option_a_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in question_data:
        return ConversationHandler.END

    question_data[user_id]["option_a"] = update.message.text
    await update.message.reply_text("📝 Please send Option B:")
    return UPLOAD_OPTION_B

async def option_b_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in question_data:
        return ConversationHandler.END

    question_data[user_id]["option_b"] = update.message.text
    await update.message.reply_text("📝 Please send Option C:")
    return UPLOAD_OPTION_C

async def option_c_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in question_data:
        return ConversationHandler.END

    question_data[user_id]["option_c"] = update.message.text
    await update.message.reply_text("📝 Please send Option D:")
    return UPLOAD_OPTION_D

async def option_d_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in question_data:
        return ConversationHandler.END

    question_data[user_id]["option_d"] = update.message.text
    await update.message.reply_text("📝 Please send the correct answer (A, B, C, or D):")
    return UPLOAD_CORRECT_ANSWER

async def correct_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in question_data:
        return ConversationHandler.END

    answer = update.message.text.upper()
    if answer not in ['A', 'B', 'C', 'D']:
        await update.message.reply_text("⚠️ Invalid answer. Please enter A, B, C, or D:")
        return UPLOAD_CORRECT_ANSWER

    course_name = question_data[user_id]["course_name"]
    
    questions = load_questions(course_name)
    questions["questions"].append({
        "question": question_data[user_id]["question"],
        "options": {
            "A": question_data[user_id]["option_a"],
            "B": question_data[user_id]["option_b"],
            "C": question_data[user_id]["option_c"],
            "D": question_data[user_id]["option_d"]
        },
        "correct_answer": answer
    })
    save_questions(course_name, questions)

    await update.message.reply_text(f"✅ MCQ question saved for course '{course_name}'!")
    del question_data[user_id]
    return ConversationHandler.END

async def cancel_question_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id in question_data:
        del question_data[user_id]
    await update.message.reply_text("❌ Question upload cancelled.")
    return ConversationHandler.END

async def view_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != OWNER_ID:
        await update.message.reply_text("🚫 You are not authorized to view questions.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: /view_questions <course_name>")
        return

    course_name = " ".join(context.args)
    questions = load_questions(course_name)

    if not questions["questions"]:
        await update.message.reply_text(f"❌ No questions found for course '{course_name}'.")
        return

    response = f"📚 Questions for '{course_name}':\n\n"
    for i, qa in enumerate(questions["questions"], 1):
        response += f"{i}. {qa['question']}\n"
        response += f"   A) {qa['options']['A']}\n"
        response += f"   B) {qa['options']['B']}\n"
        response += f"   C) {qa['options']['C']}\n"
        response += f"   D) {qa['options']['D']}\n"
        response += f"   ✅ Correct answer: {qa['correct_answer']}\n\n"

    max_length = 4000
    if len(response) > max_length:
        parts = [response[i:i+max_length] for i in range(0, len(response), max_length)]
        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(response)

async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Send daily reminder to users"""
    try:
        chat_id = context.job.data  # Changed from context.job.context
        logger.info(f"Sending daily reminder to {chat_id}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="📚 Daily reminder: Don't forget to study today! Use /courses to continue learning."
        )
    except Exception as e:
        logger.error(f"Error in daily reminder: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and notify admin"""
    logger.error(f"Update {update} caused error {context.error}")
    
    if OWNER_ID:
        tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
        tb_string = "".join(tb_list)
        
        update_str = update.to_dict() if isinstance(update, Update) else str(update)
        message = (
            f"An exception was raised while handling an update\n"
            f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}</pre>\n\n"
            f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
            f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
            f"<pre>{html.escape(tb_string)}</pre>"
        )
        
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=message,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Couldn't send error message to admin: {e}")
# Flask Server Setup
def run_flask_server():
    """Web server to keep Render service alive"""
    app = Flask(__name__)
    
    @app.route('/')
    def home():
        return "Telegram Bot is running", 200
        
    @app.route('/ping')
    def ping():
        return "pong", 200
        
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def keep_alive():
    """Pings the Flask server periodically to prevent shutdown"""
    while True:
        try:
            if 'RENDER_EXTERNAL_URL' in os.environ:
                requests.get(f"https://{os.environ['RENDER_EXTERNAL_URL']}/ping")
            time.sleep(300)  # Ping every 5 minutes
        except Exception as e:
            logger.error(f"Keep-alive ping failed: {e}")
            time.sleep(60)  # Retry after 1 minute

def main():
    load_user_progress()
    
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN provided")
        return

    application = ApplicationBuilder().token(BOT_TOKEN).build()
      # Start Flask server in a non-daemon thread (essential for Render)
    flask_thread = threading.Thread(target=run_flask_server)
    flask_thread.daemon = False  # Must be False to keep alive
    flask_thread.start()

    # Start keep-alive pinger
    keepalive_thread = threading.Thread(target=keep_alive)
    keepalive_thread.daemon = True
    keepalive_thread.start()

    # Register handlers
    reg_handler = ConversationHandler(
        entry_points=[CommandHandler("register", register)],
        states={
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, full_name_handler)],
            QUALIFICATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, qualification_handler)],
            EXPERIENCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, experience_handler)],
            PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_number_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    question_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("upload_question", start_question_upload)],
        states={
            UPLOAD_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, question_handler)],
            UPLOAD_OPTION_A: [MessageHandler(filters.TEXT & ~filters.COMMAND, option_a_handler)],
            UPLOAD_OPTION_B: [MessageHandler(filters.TEXT & ~filters.COMMAND, option_b_handler)],
            UPLOAD_OPTION_C: [MessageHandler(filters.TEXT & ~filters.COMMAND, option_c_handler)],
            UPLOAD_OPTION_D: [MessageHandler(filters.TEXT & ~filters.COMMAND, option_d_handler)],
            UPLOAD_CORRECT_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, correct_answer_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel_question_upload)]
    )

    quiz_handler = ConversationHandler(
        entry_points=[CommandHandler("next", next_slide)],
        states={
            ANSWER_Q1: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_q1_handler)],
            ANSWER_Q2: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_q2_handler)],
            ANSWER_Q3: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_q3_handler)],
            ANSWER_Q4: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_q4_handler)],
            ANSWER_Q5: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_q5_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Add all handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(reg_handler)
    application.add_handler(question_conv_handler)
    application.add_handler(quiz_handler)
    application.add_handler(CommandHandler("login", login))
    application.add_handler(CommandHandler("courses", list_courses))
    application.add_handler(CommandHandler("start_course", start_course))
    application.add_handler(CommandHandler("next", next_slide))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf_upload))
    application.add_handler(CommandHandler("view_questions", view_questions))
    application.add_handler(CommandHandler("approve", approve))
    application.add_handler(CommandHandler("reject", reject))
    
    # Add error handler
    application.add_error_handler(error_handler)

    # Schedule daily reminders (corrected version)
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_daily(
            callback=daily_reminder,
            time=datetime.time(hour=9, minute=0),  # 9 AM
            days=(0, 1, 2, 3, 4, 5, 6),  # Every day
            data=OWNER_ID,  # Changed from context=
            name="daily_reminder"
        )

    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
