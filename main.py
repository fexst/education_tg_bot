import configparser
import telebot
import json
from telebot import types
import random
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import RussianWord, EnglishWord, Visibility, create_tables


config = configparser.ConfigParser()
config.read('settings.ini', encoding='utf-8')
token_tg = config.get("TOKEN", "TOKEN")

bot = telebot.TeleBot(token_tg)


def load_words():
    with open('data_word.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    for rus, eng in data.items():
        russian_word = session.query(RussianWord).filter_by(word=rus).first()
        if not russian_word:
            russian_word = RussianWord(word=rus)
            session.add(russian_word)
            session.flush()

        english_word = EnglishWord(word=eng, id_russian=russian_word.id)
        session.add(english_word)

    session.commit()


def add_visibility(chat_id):
    all_russian_words = session.query(RussianWord).all()
    existing_word_ids = {
        v.id_russian for v in session.query(Visibility).filter_by(chatid=chat_id).all()
    }
    new_entries = [
        Visibility(chatid=chat_id, id_russian=word.id)
        for word in all_russian_words if word.id not in existing_word_ids
    ]

    if new_entries:
        session.add_all(new_entries)
        session.commit()


DSN = "postgresql://postgres:postgres!@localhost:5432/nameproject"
engine = create_engine(DSN)
create_tables(engine)
Session = sessionmaker(bind=engine)
session = Session()
load_words()


def get_random_question(chat_id):
    visible_words = (
        session.query(RussianWord)
        .join(Visibility, RussianWord.id == Visibility.id_russian)
        .filter(Visibility.chatid == chat_id)
        .all()
    )
    if not visible_words:
        return None, None, None

    question_word = random.choice(visible_words)
    correct_translation = session.query(EnglishWord).filter_by(id_russian=question_word.id).first()
    if not correct_translation:
        return None, None, None

    all_words = session.query(EnglishWord).all()
    options = [correct_translation.word] + random.sample(
        [w.word for w in all_words if w.word != correct_translation.word], 3)
    random.shuffle(options)
    return question_word.word, correct_translation.word, options


@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "Привет 👋 Давай попрактикуемся в английском языке. \n"
        "Тренировки можешь проходить в удобном темпе.\n"
        "Ты можешь добавить слова ➕ или удалить их ❌.\n"
        "Ну что, начнем!"
    )

    chat_id = message.chat.id

    with open('data_word.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    loaded_word_ids = []
    for rus, eng in data.items():
        russian_word = session.query(RussianWord).filter_by(word=rus).first()
        if russian_word:
            loaded_word_ids.append(russian_word.id)

    existing_word_ids = {
        v.id_russian for v in session.query(Visibility).filter_by(chatid=chat_id).all()
    }

    new_entries = [
        Visibility(chatid=chat_id, id_russian=word_id)
        for word_id in loaded_word_ids if word_id not in existing_word_ids
    ]

    if new_entries:
        session.add_all(new_entries)
        session.commit()

    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("➡ Далее"))
    markup.add(KeyboardButton("➕ Добавить слово"), KeyboardButton("❌ Удалить слово"))

    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == "➡ Далее")
def next_question(message):
    ask_question(message.chat.id)


def ask_question(chat_id):
    question, correct, options = get_random_question(chat_id)
    if question is None:
        bot.send_message(chat_id, "Слов пока нет, добавьте их! ➕")
        return

    markup = types.InlineKeyboardMarkup()
    for option in options:
        markup.add(types.InlineKeyboardButton(text=option, callback_data=f"answer_{option}_{correct}"))

    bot.send_message(chat_id, f"Как переводится '{question}'?", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("answer_"))
def check_answer(call):
    _, user_answer, correct_answer = call.data.split("_")

    if user_answer == correct_answer:
        bot.send_message(call.message.chat.id, "✅ Правильно!")
    else:
        bot.send_message(call.message.chat.id, "❌ Неверно. Попробуй снова!")
        return

    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("➡ Далее"))
    markup.add(KeyboardButton("➕ Добавить слово"), KeyboardButton("❌ Удалить слово"))

    bot.send_message(call.message.chat.id, "Выбери действие:", reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == "➕ Добавить слово")
def add_word(message):
    bot.send_message(message.chat.id, "Введите новое слово на русском языке:")
    bot.register_next_step_handler(message, process_add_word, message.chat.id)


def process_add_word(message, chat_id):
    russian = message.text.strip()
    rus_entry = session.query(RussianWord).filter_by(word=russian).first()
    if not rus_entry:
        rus_entry = RussianWord(word=russian)
        session.add(rus_entry)
        session.flush()

    bot.send_message(chat_id, "Теперь введите перевод на английском:")
    bot.register_next_step_handler(message, process_add_translation, chat_id, rus_entry.id)


def process_add_translation(message, chat_id, rus_id):
    english = message.text.strip()
    eng_entry = EnglishWord(word=english, id_russian=rus_id)
    session.add(eng_entry)
    session.add(Visibility(chatid=chat_id, id_russian=rus_id))
    session.commit()
    bot.send_message(chat_id, "✅ Слово добавлено!")
    ask_question(chat_id)


@bot.message_handler(func=lambda message: message.text == "❌ Удалить слово")
def remove_word(message):
    bot.send_message(message.chat.id, "Введите слово на русском для удаления:")
    bot.register_next_step_handler(message, process_remove_word, message.chat.id)


def process_remove_word(message, chat_id):
    russian = message.text.strip()
    rus_entry = session.query(RussianWord).filter_by(word=russian).first()
    if rus_entry:
        visibility_entry = session.query(Visibility).filter_by(chatid=chat_id, id_russian=rus_entry.id).first()
        if visibility_entry:
            session.delete(visibility_entry)
            session.commit()
            bot.send_message(chat_id, "✅ Слово удалено из вашего списка.")
        else:
            bot.send_message(chat_id, "❌ Это слово не в вашем списке.")
    else:
        bot.send_message(chat_id, "❌ Такого слова нет в базе.")
    ask_question(chat_id)


if __name__ == '__main__':
    print("Бот запущен")
    try:
        bot.polling()
    except Exception as e:
        print(f"Ошибка: {e}")
