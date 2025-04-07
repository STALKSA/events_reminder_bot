import nest_asyncio
nest_asyncio.apply()

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackContext,
    PicklePersistence
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, date
import logging
import asyncio

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ID стикеров (замените на свои)
STICKERS = {
    'welcome': 'CAACAgIAAxkBAAENjGtn2GGb-45eD87nqDZionFWKfLugwAC_AAD9wLID-JKwmellSruNgQ',  # ID приветственного стикера
    'birthday': 'CAACAgIAAxkBAAEOGHtn8RZ6ytZKXE03JJ5hNQcTmnK3MQACrA0AAuJ8CEocdg_Chn4uTzYE',  # ID праздничного стикера
    'holidayNewYear': 'CAACAgIAAxkBAAEOGIFn8Rdzyens1cEgidXS5Tv4wpNPJwACuwUAAj-VzArB-QxoNNQdNjYE',    # ID новый год
    'holiday23': 'CAACAgIAAxkBAAEOGIln8RfUZEG02SRE8wjmUiJDzdowvQACZAkAAnlc4glT3Md3btp8xzYE',    # ID стикера для 23 февраля
    'holiday8': 'CAACAgIAAxkBAAEOGH1n8RaD87_J8PyYugiAc5z7yd0WagACTwkAAnlc4gkq22o1wb7e2jYE',    # ID стикера 8 марта
    'holiday': 'CAACAgIAAxkBAAENjG9n2GG83yzE3tgp6gveEZHR-hxQzQAC9wAD9wLID9CX3j-K0TwONgQ',    # ID стикера праздник
}

# База данных праздников и дней рождений
holidays = {
    '01-01': {'text': '🎄 С Новым годом! 🎄', 'sticker': 'holidayNewYear'},
    '23-02': {'text': '🪖 С Днём защитника Отечества!', 'sticker': 'holiday23'},
    '08-03': {'text': '🌸 С Международным женским днём!', 'sticker': 'holiday8'},
    '09-05': {'text': '🎖️ С Днём Победы!', 'sticker': 'holiday'},
    '31-12': {'text': '🎅 С наступающим Новым годом!', 'sticker': 'holidayNewYear'}
}

birthdays = {
    '25-04': 'Имя_коллеги',
    '07-02': 'Имя_коллеги2'
}

class ReminderBot:
    def __init__(self, token):
        self.token = token
        self.persistence = PicklePersistence(filepath='reminder_bot_data')
        self.application = Application.builder() \
    .token(token) \
    .persistence(self.persistence) \
    .read_timeout(30) \
    .connect_timeout(30) \
    .pool_timeout(30) \
    .build()
        self.scheduler = AsyncIOScheduler(
            job_defaults={
        'misfire_grace_time': 60*60,  # 1 час
        'coalesce': True,
        'max_instances': 1
    }
        )

        # Регистрация обработчиков команд
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help))
        self.application.add_handler(CommandHandler("add_birthday", self.add_birthday))
        self.application.add_handler(CommandHandler("list_birthdays", self.list_birthdays))
        self.application.add_handler(CommandHandler("del_birthday", self.del_birthday))

        # Настройка меню команд
        self.application.post_init = self._setup_commands_menu

        # Настройка планировщика
        self.scheduler.add_job(
            self.send_reminders,
            'cron',
            hour=9,
            minute=30,
            timezone='Europe/Moscow'
        )

    async def _setup_commands_menu(self, application):
        """Настраивает меню команд бота"""
        commands = [
            BotCommand("start", "Начать работу с ботом"),
            BotCommand("help", "Показать справку"),
            BotCommand("add_birthday", "Добавить день рождения"),
            BotCommand("del_birthday", "Удалить день рождения"),
            BotCommand("list_birthdays", "Список дней рождений")
        ]
        await application.bot.set_my_commands(commands)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /start с отправкой стикера"""
        await update.message.reply_sticker(STICKERS['welcome'])

        user = update.effective_user
        await update.message.reply_text(
            f"Привет, {user.first_name}! Я бот-напоминалка.\n"
            "Я буду напоминать о днях рождения коллег и праздниках.\n"
            "Используй /help для списка команд."
        )

        # Сохраняем chat_id для отправки уведомлений
        chat_id = update.effective_chat.id
        if 'chat_ids' not in context.bot_data:
            context.bot_data['chat_ids'] = set()
        context.bot_data['chat_ids'].add(chat_id)

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
      """Обработчик команды /help с красивым форматированием"""
      help_text = """
      *Доступные команды:*

      */start* - Начать работу с ботом
      */help* - Показать это сообщение
      */add_birthday* - Добавить день рождения
　　  Формат: `/add_birthday ДД-ММ Имя Фамилия`
      */del_birthday* - Удалить день рождения
　　  Формат: `/del_birthday ДД-ММ`
      */list_birthdays* - Показать список дней рождений

      *Примеры:*
      `/add_birthday 15-05 Иван Петров`
      `/del_birthday 15-05`
      """
      await update.message.reply_text(
        help_text,
        parse_mode="Markdown",  # Включаем Markdown-разметку
        disable_web_page_preview=True
    )

    async def add_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Добавляет день рождения в список"""
        try:
            date_str, *name_parts = context.args
            name = ' '.join(name_parts)

            # Проверка формата даты
            datetime.strptime(date_str, '%d-%m')

            if 'birthdays' not in context.bot_data:
                context.bot_data['birthdays'] = {}
            context.bot_data['birthdays'][date_str] = name

            await update.message.reply_text(f"Добавлен день рождения: {date_str} - {name}")
        except (ValueError, IndexError):
            await update.message.reply_text("Неверный формат. Используйте: /add_birthday ДД-ММ Имя Фамилия")

    async def del_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Удаляет день рождения из списка"""
        try:
            if not context.args:
                raise ValueError("Не указана дата")

            date_str = context.args[0]

            # Проверяем формат даты
            datetime.strptime(date_str, '%d-%m')

            if 'birthdays' not in context.bot_data or date_str not in context.bot_data['birthdays']:
                await update.message.reply_text(f"❌ День рождения на {date_str} не найден")
                return

            # Удаляем запись
            del context.bot_data['birthdays'][date_str]
            await update.message.reply_text(f"✅ День рождения на {date_str} удален")

        except ValueError:
            error_message = (
                "❌ Неверный формат команды.\n"
                "Правильный формат: /del_birthday ДД-ММ\n"
                "Пример: /del_birthday 15-05"
            )
            await update.message.reply_text(error_message)

    async def list_birthdays(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показывает список дней рождений"""
        # Получаем сохраненные дни рождения
        saved_birthdays = context.bot_data.get('birthdays', {})

        # Объединяем с предопределенными днями рождения
        all_birthdays = {**birthdays, **saved_birthdays}

        if not all_birthdays:
            await update.message.reply_text("Список дней рождений пуст.")
            return

        text = "📅 Список дней рождений:\n"
        for date_str, name in sorted(all_birthdays.items()):
            text += f"{date_str} - {name}\n"

        await update.message.reply_text(text)

    async def send_reminders(self):       
     
      today = date.today().strftime('%d-%m')
      logger.info(f"Проверка напоминаний на {today}")

      try:
          
          bot_data = self.application.bot_data
        
          if 'chat_ids' not in bot_data or not bot_data['chat_ids']:
              logger.warning("Нет активных чатов для отправки") 
              return

        # Объединяем предопределенные и сохраненные дни рождения
          all_birthdays = {**birthdays, **bot_data.get('birthdays', {})}
        
        # Проверка дней рождений
          if today in all_birthdays:
            name = all_birthdays[today]
            logger.info(f"Найдено день рождения: {name}")
            for chat_id in bot_data['chat_ids']:
                try:
                    await self.application.bot.send_sticker(
                        chat_id=chat_id,
                        sticker=STICKERS['birthday']
                    )
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=f"🎉 Сегодня день рождения у {name}! Поздравляем!"
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки в чат {chat_id}: {e}")

        # Проверка праздников
          if today in holidays:
            holiday = holidays[today]
            for chat_id in bot_data['chat_ids']:
                try:
                    await self.application.bot.send_sticker(
                        chat_id=chat_id,
                        sticker=STICKERS[holiday['sticker']]
                    )
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=holiday['text']
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки праздника в чат {chat_id}: {e}")
                    
      except Exception as e:
        logger.error(f"Критическая ошибка в send_reminders: {e}", exc_info=True)
                    

    def run(self):
        """Запускает бота с обработкой ошибок"""
        self.scheduler.start()
        
        try:
            # Убедимся, что вебхук удален
            asyncio.get_event_loop().run_until_complete(
                self.application.bot.delete_webhook(drop_pending_updates=True)
            )
            
            # Запускаем polling с обработкой ошибок
            self.application.run_polling(
                close_loop=False,
                stop_signals=None,
                allowed_updates=None,
                drop_pending_updates=True
            )
        except Exception as e:
            logger.error(f"Ошибка при работе бота: {e}")
        finally:
            self.scheduler.shutdown()

if __name__ == '__main__':
    # Установите nest-asyncio для Jupyter
    !pip install nest-asyncio

    # Прямая передача токена
    token = 'TELEGRAM_TOKEN'

    bot = ReminderBot(token)
    bot.run()