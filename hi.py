import os
from transformers import pipeline
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

# 🔐 Replace with your actual Telegram ID (as the bot owner)
OWNER_ID = 6694915001
BOT_TOKEN = '7910184229:AAFAVUchZ4NwgWpqFYNtZHEL6Da14FtFkxY'
quiz_generator = pipeline('text2text-generation', model='google/flan-t5-small')

# Conversation states for registration
FULL_NAME, QUALIFICATION, EXPERIENCE, PHONE_NUMBER = range(4)

# Global stores
user_progress = {}
authenticated_users = set()
user_data = {}
pending_approvals = {}
TEST_INTERVAL = 5

def load_user_progress():
    global user_progress
    if os.path.exists("user_data.json"):
        with open("user_data.json", "r", encoding="utf-8") as f:
            user_progress = json.load(f)

def load_users():
    if os.path.exists("users.json"):
        with open("users.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_user_progress():
    with open("user_data.json", "w", encoding="utf-8") as f:
        json.dump(user_progress, f, indent=4)

def save_users(users):
    with open("users.json", "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text("❌ Registration cancelled.")
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
    if str(update.message.from_user.id) not in authenticated_users:
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
async def generate_slide_questions(slides: list, start_idx: int, end_idx: int):
    recent_slides = slides[start_idx:end_idx+1]
    slide_texts = [slide['text'] for slide in recent_slides]
    context = "\n".join(slide_texts)
    
    prompt = f"Generate 3 multiple choice questions based on the following content:\n\n{context}\n\n" \
             "Format each question as:\n" \
             "Q1. [Question text]\n" \
             "A) [Option A]\n" \
             "B) [Option B]\n" \
             "C) [Option C]\n" \
             "D) [Option D]\n" \
             "Correct: [Correct option letter]"
    
    try:
        result = quiz_generator(prompt, max_length=500, num_return_sequences=1)
        return result[0]['generated_text']
    except Exception as e:
        print(f"Error generating questions: {str(e)}")
        return None
   
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

    if not os.path.exists(slides_path):
        await update.message.reply_text("❌ Course data not found. Please contact admin.")
        return

    try:
        with open(slides_path, "r", encoding="utf-8") as f:
            course_data = json.load(f)
    except Exception as e:
        await update.message.reply_text(f"❌ Error loading course: {str(e)}")
        return

    current_index = user_progress[user_id]["slide_index"]
    
    # Check if we need to conduct a test before showing the next slide
    if current_index >= 0 and (current_index + 1) % TEST_INTERVAL == 0:
        test_start_idx = max(0, current_index - TEST_INTERVAL + 1)
        test_end_idx = current_index
        questions = await generate_slide_questions(course_data["slides"], test_start_idx, test_end_idx)
        
        if questions:
            await update.message.reply_text(
                f"📝 Time for a quick test on slides {test_start_idx+1}-{test_end_idx+1}!\n\n" +
                questions + 
                "\n\nReview these questions and type /next when ready to continue."
            )
            user_progress[user_id]["awaiting_test_completion"] = True
            save_user_progress()
            return
        else:
            await update.message.reply_text("⚠️ Couldn't generate test questions. Continuing to next slide...")

    # Only increment slide index if we're not waiting for test completion
    if not user_progress[user_id].get("awaiting_test_completion", False):
        user_progress[user_id]["slide_index"] += 1
        current_index = user_progress[user_id]["slide_index"]
    else:
        user_progress[user_id]["awaiting_test_completion"] = False

    if current_index >= len(course_data["slides"]):
        await update.message.reply_text("🎉 You've completed this course!")
        del user_progress[user_id]["current_course"]
        del user_progress[user_id]["slide_index"]
        save_user_progress()
        return

    save_user_progress()
    await send_slide(update, course_data["slides"][current_index], course_name)

async def send_slide(update: Update, slide: dict, course_name: str):
    try:
        # Clean the text to prevent Markdown parsing errors
        def clean_markdown(text):
            if not text:
                return ""
            # Escape Markdown special characters
            for char in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
                text = text.replace(char, f'\\{char}')
            return text

        # Prepare slide content
        page_content = clean_markdown(slide.get('page_content', 'Slide'))
        slide_text = clean_markdown(slide.get('text', ''))
        
        # Split long messages to avoid Telegram's length limit (4096 characters)
        max_length = 4000  # Conservative limit to account for Markdown formatting
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

        # Send images if they exist
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
        await update.message.reply_text(
            "📄 Here's the slide content (formatting simplified due to error):\n\n" + 
            slide.get('text', 'No content available')
        )
        print(f"Error sending slide: {str(e)}")

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

    course_json = {
        "course_name": course_name,
        "total_slides": len(slides),
        "slides": slides
    }

    with open(os.path.join(course_dir, "slides.json"), "w", encoding="utf-8") as f:
        json.dump(course_json, f, indent=4)

    await update.message.reply_text(f"✅ PDF processed successfully! Course '{course_name}' created.")

async def generate_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != OWNER_ID:
        await update.message.reply_text("🚫 You are not authorized to generate tests.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: /generate_tests <course_name>")
        return

    course_name = " ".join(context.args)
    course_dir = os.path.join("courses", course_name)
    slides_path = os.path.join(course_dir, "slides.json")

    if not os.path.exists(slides_path):
        await update.message.reply_text(f"❌ Course '{course_name}' not found.")
        return

    await update.message.reply_text("🤖 Generating quizzes and technical tests... Please wait.")

    try:
        with open(slides_path, "r", encoding="utf-8") as f:
            course_data = json.load(f)

        all_text = "\n".join(slide["text"] for slide in course_data["slides"])

        # Generate MCQs
        quiz_prompt = f"Create 5 multiple choice questions with 4 options each based on:\n\n{all_text}\nMake them educational."
        quiz_output = quiz_generator(quiz_prompt, max_length=500, num_return_sequences=1)
        mcq_text = quiz_output[0]['generated_text']

        # Generate Technical Tests
        tech_prompt = f"Create 3 technical test questions with short answers based on:\n\n{all_text}\nMake them simple and technical."
        tech_output = quiz_generator(tech_prompt, max_length=400, num_return_sequences=1)
        tech_text = tech_output[0]['generated_text']

        # Save to files
        with open(os.path.join(course_dir, "questions.txt"), "w", encoding="utf-8") as f:
            f.write(mcq_text)
        with open(os.path.join(course_dir, "technical_tests.txt"), "w", encoding="utf-8") as f:
            f.write(tech_text)

        await update.message.reply_text(f"✅ Quiz and Technical Tests generated for '{course_name}'!")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error during generation: {str(e)}")

def main():
    load_user_progress()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(reg_handler)
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("courses", list_courses))
    app.add_handler(CommandHandler("start_course", start_course))
    app.add_handler(CommandHandler("next", next_slide))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf_upload))
    app.add_handler(CommandHandler("generate_tests", generate_tests))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))

    app.add_error_handler(lambda update, context: print(f"Update {update} caused error {context.error}"))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()