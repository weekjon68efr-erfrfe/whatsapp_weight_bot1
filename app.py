from flask import Flask, request, jsonify
import os
from datetime import datetime
from database import Database
from config import Config
from ocr_utils import extract_weight_from_image
import logging

app = Flask(__name__)
db = Database()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GreenApiClient:
    """Клиент для работы с Green API"""
    
    def __init__(self, id_instance: str, api_token: str):
        self.id_instance = id_instance
        self.api_token = api_token
        self.base_url = "https://api.green-api.com"
    
    def send_message(self, chat_id: str, message: str) -> dict:
        """Отправить текстовое сообщение в WhatsApp"""
        import requests
        
        # Если chat_id уже содержит @g.us (группа) или @c.us (личный чат), не добавляем суффикс
        if not chat_id.endswith('@g.us') and not chat_id.endswith('@c.us'):
            chat_id = f"{chat_id}@c.us"
        
        url = f"{self.base_url}/waInstance{self.id_instance}/sendMessage/{self.api_token}"
        data = {
            "chatId": chat_id,
            "message": message
        }
        
        try:
            print(f"📤 Отправка сообщения на {chat_id}")
            response = requests.post(url, json=data, timeout=10)
            print(f"✅ Ответ Green API: {response.status_code}")
            try:
                response_json = response.json()
                print(f"   Ответ: {response_json}")
                return response_json
            except:
                print(f"   Текст ответа: {response.text}")
                return None
        except Exception as e:
            print(f"❌ Ошибка отправки: {e}")
            return None
    
    def send_file_by_url(self, chat_id: str, url_file: str, file_name: str, caption: str = None) -> dict:
        """Отправить файл по URL с опциональной подписью"""
        import requests
        
        # Если chat_id уже содержит @g.us (группа) или @c.us (личный чат), не добавляем суффикс
        if not chat_id.endswith('@g.us') and not chat_id.endswith('@c.us'):
            chat_id = f"{chat_id}@c.us"
        
        url = f"{self.base_url}/waInstance{self.id_instance}/sendFileByUrl/{self.api_token}"
        data = {
            "chatId": chat_id,
            "urlFile": url_file,
            "fileName": file_name
        }
        
        # Добавляем caption (подпись) если указана
        if caption:
            data["caption"] = caption
        
        try:
            response = requests.post(url, json=data, timeout=10)
            return response.json()
        except Exception as e:
            print(f"❌ Ошибка отправки файла: {e}")
            return None


# Инициализация Green API клиента
whatsapp = GreenApiClient(
    Config.GREEN_API_ID_INSTANCE,
    Config.GREEN_API_TOKEN_INSTANCE
)


# ==================== ГЛАВНОЕ МЕНЮ ====================

def show_main_menu(phone: str) -> str:
    """Показать главное меню"""
    db.clear_user_state(phone)
    driver = db.get_driver(phone)
    
    if not driver or not driver.get('is_registered', 0):
        return """
Вы не зарегистрированы в системе.

Отправьте "да" для регистрации
"""
    
    return f"""
Выберите действие:
1 - Новый отчет о взвешивании
2 - Изменить номер машины
3 - Переоформить регистрацию
0 - Главное меню
"""


# ==================== РЕГИСТРАЦИЯ ВОДИТЕЛЯ ====================

def start_registration(phone: str) -> str:
    """Начать процесс регистрации"""
    db.set_user_state(phone, 'registration_name')
    
    return """
Регистрация водителя

Добро пожаловать! Для начала работы нужно зарегистрироваться.

Введите ваше ФИО (полное имя):
"""


def handle_registration_name(phone: str, text: str) -> str:
    """Обработка ввода ФИО при регистрации"""
    text_lower = text.lower().strip()
    
    # Проверяем команды
    if text_lower == "0" or text_lower == "меню":
        return show_main_menu(phone)
    
    full_name = text.strip()
    
    if len(full_name) < 3:
        return "Пожалуйста, введите полное имя (минимум 3 символа)"
    
    # Сохраняем имя во временные данные
    db.set_user_state(phone, 'registration_phone', temp_data={'full_name': full_name})
    
    return f"""
ФИО: {full_name}

Теперь введите ваш личный номер телефона:
Пример: 89123456789
"""


def handle_registration_phone(phone: str, text: str) -> str:
    """Обработка ввода номера телефона при регистрации"""
    text_lower = text.lower().strip()
    
    # Проверяем команды
    if text_lower == "0" or text_lower == "меню":
        return show_main_menu(phone)
    
    # Очищаем номер
    phone_clean = ''.join(filter(str.isdigit, text))
    
    if len(phone_clean) < 6:  # Минимум 6 цифр
        return "Неверный номер телефона. Введите еще раз (например: 89123456789)"
    
    state = db.get_user_state(phone)
    temp_data = state['temp_data'] if isinstance(state['temp_data'], dict) else {}
    
    full_name = temp_data.get('full_name', '?')
    
    # Сохраняем телефон и переходим к номеру машины
    temp_data['personal_phone'] = phone_clean
    db.set_user_state(phone, 'registration_truck', temp_data=temp_data)
    
    return "Введите номер вашей машины:"


def handle_registration_truck(phone: str, text: str) -> str:
    """Обработка ввода номера машины при регистрации"""
    text_lower = text.lower().strip()
    
    # Проверяем команды
    if text_lower == "0" or text_lower == "меню":
        return show_main_menu(phone)
    
    truck_number = text.upper().strip()
    
    if len(truck_number) < 3:
        return "Введите правильный номер машины"
    
    state = db.get_user_state(phone)
    temp_data = state['temp_data'] if isinstance(state['temp_data'], dict) else {}
    
    full_name = temp_data.get('full_name', '?')
    personal_phone = temp_data.get('personal_phone', '')
    
    # Регистрируем водителя с номером машины
    success = db.register_driver(phone, full_name, personal_phone, truck_number)
    
    if success:
        db.clear_user_state(phone)
        return f"""
Регистрация завершена!

Данные:
ФИО: {full_name}
Телефон: +{personal_phone}
Машина: {truck_number}

Отправьте "1" для заполнения нового груза
"""
    else:
        return "Ошибка при регистрации. Попробуйте еще раз."


# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================

def process_message(phone: str, text: str, has_media: bool = False) -> str:
    """Главная функция обработки сообщений"""
    
    # Сначала проверяем, есть ли медиа
    if has_media and text:
        print(f"🔍 Обработка медиа от {phone}")
        # Если ожидаем фото - обрабатываем его
        state = db.get_user_state(phone)
        print(f"   Текущее состояние: {state}")
        if state and state['state'] == 'awaiting_photo':
            print(f"   ✅ Ожидаем фото - обрабатываем")
            # Медиа данные сохранены в состояние на этапе webhook
            return handle_photo_received(phone, has_media=True)
        else:
            print(f"   ❌ Фото не ожидается (состояние: {state['state'] if state else 'нет'})")
        # Иначе игнорируем медиа
        return "❌ Сейчас фото не нужны. Отправьте текст."
    
    # Сохраняем оригинальный текст
    text_original = text.strip()
    # Для команд используем нижний регистр
    text_lower = text_original.lower()
    
    # Команды верхнего уровня
    if text_lower == "0" or text_lower == "меню":
        return show_main_menu(phone)
    
    if text_lower == "3" or text_lower == "регистрация":
        db.clear_user_state(phone)
        return start_registration(phone)
    
    # Проверяем, зарегистрирован ли водитель
    if not db.is_driver_registered(phone):
        # Если не зарегистрирован - проверяем его состояние регистрации
        state = db.get_user_state(phone)
        
        if not state:
            # Начинаем регистрацию
            db.clear_user_state(phone)
            return start_registration(phone)
        
        if state['state'] == 'registration_name':
            return handle_registration_name(phone, text_original)
        elif state['state'] == 'registration_phone':
            return handle_registration_phone(phone, text_original)
        elif state['state'] == 'registration_truck':
            return handle_registration_truck(phone, text_original)
        
        # Если не понятно - в начало
        return start_registration(phone)
    
    # Водитель зарегистрирован - проверяем состояние отчета или регистрации
    state = db.get_user_state(phone)
    
    # Сначала проверяем, может ли быть процесс переоформления регистрации
    if state and state['state'] in ['registration_name', 'registration_phone', 'registration_truck']:
        if state['state'] == 'registration_name':
            return handle_registration_name(phone, text_original)
        elif state['state'] == 'registration_phone':
            return handle_registration_phone(phone, text_original)
        elif state['state'] == 'registration_truck':
            return handle_registration_truck(phone, text_original)
    
    # Команда "2" - изменить номер машины
    if text_lower == "2":
        db.set_user_state(phone, 'changing_truck')
        return "Введите новый номер машины:"
    
    # Если текст = "1" - начинаем новый отчет (берем машину из профиля)
    if text_lower == "1":
        driver = db.get_driver(phone)
        truck_number = driver.get('truck_number') if driver else None
        
        if truck_number:
            # Переходим сразу к имени клиента
            personal_phone = driver.get('personal_phone', '')
            full_name = driver.get('full_name', '?')
            
            db.set_user_state(phone, 'awaiting_client', temp_data={
                'truck_number': truck_number,
                'driver_name': full_name,
                'driver_phone': personal_phone
            })
            return "Введите имя клиента:"
        else:
            # Если номера машины нет - просим его установить
            return "Номер машины не установлен. Выполните пункт меню 2 для установки номера машины."
    
    if state:
        temp_data = state['temp_data'] if isinstance(state['temp_data'], dict) else {}
        
        if state['state'] == 'changing_truck':
            truck_number = text_original.upper().strip()
            if len(truck_number) < 3:
                return "Введите правильный номер машины"
            db.update_driver(phone, truck_number=truck_number)
            db.clear_user_state(phone)
            return f"Номер машины изменен на {truck_number}\n\nОтправьте 0 для главного меню"
        elif state['state'] == 'awaiting_client':
            return handle_client_name(phone, text_original)
        elif state['state'] == 'awaiting_photo':
            # Получаем message_data из temp_data если есть медиа
            message_data = temp_data.get('media_data', {}) if has_media else None
            return handle_photo_received(phone, has_media, message_data)
        elif state['state'] == 'awaiting_manual_weight':
            # Пользователь либо вводит вес, либо отправляет новое фото
            if has_media:
                # Новое фото - обрабатываем его
                message_data = temp_data.get('media_data', {})
                return handle_photo_received(phone, True, message_data)
            else:
                # Попытка ввести вес вручную
                return handle_manual_weight_input(phone, text_original)
        elif state['state'] == 'awaiting_confirmation':
            return handle_confirmation(phone, text_original)
        elif state['state'] == 'awaiting_stats_truck':
            # Пользователь вводит номер машины для статистики
            truck_number = text.upper().strip()
            db.clear_user_state(phone)
            vehicle = db.get_vehicle(truck_number)
            history = db.get_vehicle_history(truck_number, limit=5)
            
            if not vehicle:
                return f"❌ Машина {truck_number} не найдена"
            
            response = f"""
*СТАТИСТИКА МАШИНЫ*
*{truck_number}*

Последний вес: {vehicle['last_weight']:.0f} кг
Последняя заправка: {vehicle['last_station'] or '?'}
Последнее взвешивание: {vehicle['last_weighing_date'] or 'нет данных'}

*ПОСЛЕДНИЕ ОТЧЕТЫ:*
"""
            
            if history:
                for i, item in enumerate(history, 1):
                    date_obj = datetime.fromisoformat(item['created_at'])
                    date_str = date_obj.strftime('%d.%m %H:%M')
                    
                    response += f"\n{i}. {date_str}\n"
                    response += f"   Водитель: {item['driver_name']}\n"
                    response += f"   Клиент: {item.get('client_name', '?')}\n"
                    response += f"   Вес: {item['current_weight']:.0f} кг\n"
                    response += f"   Разница: {item['weight_difference']:.0f} кг\n"
            else:
                response += "\nНет отчетов\n"
            
            response += "\n0 - Главное меню\n"
            return response
    
    return "Не понимаю команду. Отправьте 0 для меню"


# ==================== ПРОЦЕСС ЗАПОЛНЕНИЯ ОТЧЕТА ====================

def handle_client_name(phone: str, text: str) -> str:
    """Обработка имени клиента"""
    state = db.get_user_state(phone)
    temp_data = state['temp_data'] if isinstance(state['temp_data'], dict) else {}
    
    client_name = text.strip()
    
    if len(client_name) < 2:
        return "Введите имя клиента"
    
    temp_data['client_name'] = client_name
    # Пропускаем вопрос о весе и сразу переходим к фото
    db.set_user_state(phone, 'awaiting_photo', temp_data=temp_data)
    
    return "Отправьте фото показаний весов:"


def handle_manual_weight_input(phone: str, text: str) -> str:
    """Обработка ручного ввода веса, когда OCR не смог распознать"""
    text_clean = text.strip()
    
    # Очищаем текст от букв и спецсимволов
    weight_str = ''.join(c for c in text_clean if c.isdigit() or c == '.')
    
    try:
        weight = float(weight_str)
        
        # Проверяем диапазон разумного веса
        if weight < 100:  # Менее 100 кг - явно ошибка
            return "⚠️ Вес слишком мал (нужно 5000-60000 кг)\n\nПопробуйте еще раз или отправьте новое фото"
        
        if weight > 150000:  # Более 150 тонн - явно ошибка
            return "⚠️ Вес слишком велик (нужно 5000-60000 кг)\n\nПопробуйте еще раз или отправьте новое фото"
        
        # Вес принят - переходим к подтверждению
        state = db.get_user_state(phone)
        temp_data = state['temp_data'] if isinstance(state['temp_data'], dict) else {}
        
        current_weight = weight
        temp_data['current_weight'] = current_weight
        temp_data['photo_received'] = True
        temp_data['weight_manual_input'] = True  # Отмечаем, что вес введен вручную
        
        # Получаем предыдущий вес машины
        truck_number = temp_data.get('truck_number', '')
        previous_weight = db.get_last_weight(truck_number)
        temp_data['previous_weight'] = previous_weight
        
        # Вычисляем разницу
        weight_difference = current_weight - previous_weight
        temp_data['weight_difference'] = weight_difference
        
        print(f"✅ Вес введен вручную: {current_weight} кг")
        print(f"   Текущий: {current_weight} кг")
        print(f"   Предыдущий: {previous_weight} кг")
        print(f"   Разница: {weight_difference:+.0f} кг")
        
        # Переходим к подтверждению
        db.set_user_state(phone, 'awaiting_confirmation', temp_data=temp_data)
        
        # Формируем сообщение подтверждения
        return f"""✅ Подтверждение отчета

Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}
Телефон: {temp_data.get('driver_phone', '?')}
Машина: {truck_number}
Клиент: {temp_data.get('client_name', '?')}

*Вес ВРУЧНУЮ введен:* {current_weight:.0f} кг
Вес предыдущий: {previous_weight:.0f} кг
Разница: {weight_difference:+.0f} кг

Напишите "да" для сохранения
Напишите "нет" для отмены
"""
    
    except ValueError:
        return "❌ Не понимаю. Напишите число, например: 15000\n\nИли отправьте новое фото весов"



def handle_photo_received(phone: str, has_media: bool, message_data: dict = None) -> str:
    """Обработка полученного фото с распознаванием веса"""
    if not has_media:
        return "Пожалуйста, отправьте фото. Просто загрузите изображение в чат."
    
    state = db.get_user_state(phone)
    temp_data = state['temp_data'] if isinstance(state['temp_data'], dict) else {}
    
    print(f"📸 Обработка фото от {phone}")
    
    # Сохраняем информацию о медиа
    if message_data:
        temp_data['media_data'] = message_data
        print(f"   Сохранены данные о фото: {message_data.keys()}")
    
    # Попытаемся скачать и обработать фото
    current_weight = None
    photo_path = None
    
    try:
        # Получаем URL фотографии
        if 'fileMessageData' in message_data:
            photo_url = message_data.get('fileMessageData', {}).get('downloadUrl')
        elif 'imageMessageData' in message_data:
            photo_url = message_data.get('imageMessageData', {}).get('downloadUrl')
        elif 'photoMessageData' in message_data:
            photo_url = message_data.get('photoMessageData', {}).get('downloadUrl')
        else:
            photo_url = None
        
        if photo_url:
            print(f"📥 Скачивание фото с URL: {photo_url}")
            
            # Скачиваем фото
            import requests
            response = requests.get(photo_url, timeout=30)
            
            if response.status_code == 200:
                # Сохраняем фото локально
                from datetime import datetime
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                photo_path = f'uploads/photos/{phone}_{timestamp}.jpg'
                os.makedirs('uploads/photos', exist_ok=True)
                
                with open(photo_path, 'wb') as f:
                    f.write(response.content)
                
                print(f"✅ Фото сохранено: {photo_path}")
                
                # Распознаем вес с помощью OCR
                print(f"🔍 Распознавание веса с фотографии...")
                weight, ocr_message, ocr_details = extract_weight_from_image(photo_path)
                
                if weight is not None:
                    current_weight = weight
                    print(f"✅ Вес распознан из фото: {weight} кг")
                    temp_data['current_weight'] = current_weight
                    temp_data['photo_received'] = True
                    temp_data['ocr_details'] = ocr_details  # Сохраняем детали распознавания
                    
                    # Получаем предыдущий вес машины
                    truck_number = temp_data.get('truck_number', '')
                    previous_weight = db.get_last_weight(truck_number)
                    temp_data['previous_weight'] = previous_weight
                    
                    # Вычисляем разницу
                    weight_difference = current_weight - previous_weight
                    temp_data['weight_difference'] = weight_difference
                    temp_data['photo_path'] = photo_path
                    
                    print(f"   Текущий: {current_weight} кг")
                    print(f"   Предыдущий: {previous_weight} кг")
                    print(f"   Разница: {weight_difference:+.0f} кг")
                    
                    # Переходим к подтверждению
                    db.set_user_state(phone, 'awaiting_confirmation', temp_data=temp_data)
                    
                    # Формируем сообщение подтверждения
                    return f"""Подтверждение отчета

Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}
Телефон: {temp_data.get('driver_phone', '?')}
Машина: {truck_number}
Клиент: {temp_data.get('client_name', '?')}
Вес новый: {current_weight:.0f} кг
Вес предыдущий: {previous_weight:.0f} кг
Разница: {weight_difference:+.0f} кг

Напишите "да" для сохранения
Напишите "нет" для отмены
"""
                else:
                    # Вес не распознался - предлагаем несколько вариантов
                    print(f"❌ Вес не распознан: {ocr_message}")
                    
                    # Переходим в режим ручного ввода веса с опцией повторной попытки
                    db.set_user_state(phone, 'awaiting_manual_weight', temp_data=temp_data)
                    
                    return f"""{ocr_message}

💡 *Варианты решения:*

1️⃣ *Отправьте НОВОЕ фото* - лучше сфокусировано на табло весов
2️⃣ *Введите вес вручную* - просто напишите число (например: 15000)

⚠️ Важно: фото должно показывать четкие цифры на табло весов"""
            else:
                print(f"❌ Ошибка при скачивании фото: {response.status_code}")
                return "❌ Ошибка при скачивании фото. Попробуйте еще раз."
        else:
            print(f"❌ URL фото не найден в сообщении")
            return "❌ Не удалось получить фото. Попробуйте еще раз."
    
    except Exception as e:
        print(f"❌ Ошибка обработки фото: {e}")
        import traceback
        traceback.print_exc()
        return f"""❌ Ошибка при обработке фото: {str(e)}

Попробуйте отправить фото еще раз"""




def handle_confirmation(phone: str, text: str) -> str:
    """Обработка подтверждения сохранения отчета"""
    state = db.get_user_state(phone)
    temp_data = state['temp_data'] if isinstance(state['temp_data'], dict) else {}
    
    # Проверяем "нет" - отмена отчета
    if text.lower() in ['нет', 'no', 'н', 'n']:
        db.clear_user_state(phone)
        return "Отчет отменен.\n\nОтправьте 1 для заполнения нового груза или 0 для главного меню"
    
    # Проверяем "да" - сохранение отчета
    if text.lower() not in ['да', 'yes', 'д', 'y']:
        return "Пожалуйста, напишите 'да' для сохранения или 'нет' для отмены"
    
    # Сохраняем отчет в БД
    driver = db.get_driver(phone)
    
    weighing_data = {
        'driver_phone': phone,
        'truck_number': temp_data.get('truck_number', ''),
        'driver_name': driver['full_name'] if driver else '',
        'client_name': temp_data.get('client_name', ''),
        'current_weight': temp_data.get('current_weight', 0),
        'station_name': '',  # Не используется в упрощенном потоке
        'photo_received': temp_data.get('photo_received', False)
    }
    
    result = db.save_weighing(weighing_data)
    
    if result:
        # Отправляем отчет в группу (с фото если есть)
        send_report_to_group(phone, temp_data, driver)
        
        db.clear_user_state(phone)
        
        return """
Отчет сохранен и отправлен!

Отправьте "1" для заполнения нового груза
0 - Главное меню
"""
    else:
        return "Ошибка при сохранении отчета. Попробуйте еще раз."


# ==================== ОТПРАВКА ОТЧЕТОВ ====================

def send_report_to_group(phone: str, temp_data: dict, driver: dict):
    """Отправить отчет в WhatsApp-группу"""
    truck_number = temp_data.get('truck_number', '?')
    client_name = temp_data.get('client_name', '?')
    driver_phone = temp_data.get('driver_phone', '?')
    driver_name = (driver['full_name'] if driver else '?').upper()
    previous_weight = temp_data.get('previous_weight', 0)
    current_weight = temp_data.get('current_weight', 0)
    weight_diff = temp_data.get('weight_difference', 0)
    photo_received = temp_data.get('photo_received', False)
    media_data = temp_data.get('media_data', {})
    
    # Формируем текст отчета с жирным шрифтом для водителя
    report = f"""*{driver_name}*  *{driver_phone}*

Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}
Машина: {truck_number}
Клиент: {client_name}

Вес новый: {current_weight:.0f} кг
Вес предыдущий: {previous_weight:.0f} кг
Разница: {weight_diff:+.0f} кг"""
    
    print(f"Отправка отчета в группу:\n{report}")
    
    # Получаем ID группы из конфига
    GROUP_ID = Config.GROUP_ID
    
    if GROUP_ID and GROUP_ID != "":
        print(f"Отправка в группу: {GROUP_ID}")
        
        # Если есть фото - отправляем его вместе с отчетом как подпись
        if photo_received and media_data:
            try:
                photo_url = None
                if 'fileMessageData' in media_data:
                    file_data = media_data.get('fileMessageData', {})
                    photo_url = file_data.get('downloadUrl') or file_data.get('url')
                
                if photo_url:
                    print(f"Отправка фото с отчетом по URL: {photo_url}")
                    # Отправляем фото с подписью (текст отчета)
                    whatsapp.send_file_by_url(GROUP_ID, photo_url, "report.jpg", caption=report)
                else:
                    # Если URL не найден, отправляем просто текст
                    print(f"URL фото не найден, отправляем текст отчета")
                    whatsapp.send_message(GROUP_ID, report)
            except Exception as e:
                print(f"Ошибка при отправке фото: {e}")
                # Отправляем текст если фото не получилось
                whatsapp.send_message(GROUP_ID, report)
        else:
            # Отправляем только текст отчета
            whatsapp.send_message(GROUP_ID, report)
    else:
        print(f"GROUP_ID не установлен в .env файле")
        print(f"   Отчет НЕ отправлен в группу")


# ==================== ПРОСМОТР ИСТОРИИ ====================

def show_history(phone: str) -> str:
    """Показать историю отчетов текущего водителя"""
    history = db.get_driver_history(phone, limit=5)
    
    if not history:
        return "📭 У вас пока нет отчетов."
    
    response = "📋 *ВАШИ ПОСЛЕДНИЕ ОТЧЕТЫ*\n\n"
    
    for i, item in enumerate(history, 1):
        date_obj = datetime.fromisoformat(item['created_at'])
        date_str = date_obj.strftime('%d.%m %H:%M')
        
        response += f"{i}. {date_str}\n"
        response += f"   {item['truck_number']}\n"
        response += f"   Клиент: {item.get('client_name', '?')}\n"
        response += f"   {item['station_name']}\n"
        response += f"   Вес: {item['current_weight']:.0f} кг\n"
        response += f"   Разница: {item['weight_difference']:.0f} кг\n\n"
    
    return response


def show_vehicle_stats(phone: str) -> str:
    """Показать статистику по машине"""
    # Получаем текущее состояние
    state = db.get_user_state(phone)
    
    # Если есть состояние с номером машины
    truck_number = None
    if state and isinstance(state['temp_data'], dict):
        truck_number = state['temp_data'].get('truck_number', '')
    
    # Если нет номера машины в состоянии - просим его ввести
    if not truck_number:
        # Сохраняем состояние для ввода машины
        db.set_user_state(phone, 'awaiting_stats_truck')
        return "Введите номер машины для просмотра статистики:\nПример: А123БВ777"
    
    vehicle = db.get_vehicle(truck_number)
    history = db.get_vehicle_history(truck_number, limit=5)
    
    if not vehicle:
        return f"❌ Машина {truck_number} не найдена"
    
    response = f"""
*СТАТИСТИКА МАШИНЫ*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
*{truck_number}*

Последний вес: {vehicle['last_weight']:.0f} кг
Последняя заправка: {vehicle['last_station'] or '?'}
Последнее взвешивание: {vehicle['last_weighing_date'] or 'нет данных'}

*ПОСЛЕДНИЕ ОТЧЕТЫ:*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    if history:
        for i, item in enumerate(history, 1):
            date_obj = datetime.fromisoformat(item['created_at'])
            date_str = date_obj.strftime('%d.%m %H:%M')
            
            response += f"\n{i}. {date_str}\n"
            response += f"   Водитель: {item['driver_name']}\n"
            response += f"   Клиент: {item.get('client_name', '?')}\n"
            response += f"   Вес: {item['current_weight']:.0f} кг\n"
            response += f"   Разница: {item['weight_difference']:.0f} кг\n"
    else:
        response += "\nНет отчетов\n"
    
    return response


# ==================== ВЕБХУК ====================

@app.route('/webhook', methods=['POST'])
def webhook():
    """Получение сообщений от Green API"""
    try:
        data = request.json
        print(f"📨 Получены данные от Green API")
        
        webhook_type = data.get("typeWebhook")
        
        if webhook_type == "incomingMessageReceived":
            message_data = data.get("messageData", {})
            sender_data = data.get("senderData", {})
            
            # Проверяем наличие текстового сообщения
            text = None
            has_media = False
            
            if "textMessageData" in message_data:
                text = message_data["textMessageData"]["textMessage"]
                print(f"📝 Текстовое сообщение: {text}")
            elif "extendedTextMessageData" in message_data:
                # Расширенное текстовое сообщение (с цитатой, форматированием и т.д.)
                text = message_data["extendedTextMessageData"].get("text", "")
                print(f"📝 Расширенное текстовое сообщение: {text}")
            elif "imageMessageData" in message_data or "documentMessageData" in message_data or "photoMessageData" in message_data or "fileMessageData" in message_data:
                # Есть медиа (фото, документ и т.д.)
                has_media = True
                text = "фото"  # Просто флаг для системы
                print(f"📸 Получено фото/медиа")
                print(f"   Полные данные сообщения: {message_data}")
                if "imageMessageData" in message_data:
                    print(f"   Тип: imageMessageData - {message_data['imageMessageData']}")
                if "photoMessageData" in message_data:
                    print(f"   Тип: photoMessageData - {message_data['photoMessageData']}")
                if "documentMessageData" in message_data:
                    print(f"   Тип: documentMessageData - {message_data['documentMessageData']}")
                if "fileMessageData" in message_data:
                    print(f"   Тип: fileMessageData - {message_data['fileMessageData']}")
            else:
                print(f"⚠️ Неизвестный тип сообщения, доступные ключи: {message_data.keys()}")
                return jsonify({"status": "ok"}), 200
            
            # Получаем номер телефона
            chat_id = sender_data.get("chatId", "")
            phone = chat_id.split("@")[0]
            
            if not text:
                return jsonify({"status": "ok"}), 200
            
            print(f"📱 Сообщение от {phone}: {text}")
            
            # Сохраняем информацию о медиа если есть
            if has_media:
                state = db.get_user_state(phone)
                if state and state['state'] == 'awaiting_photo':
                    temp_data = state['temp_data'] if isinstance(state['temp_data'], dict) else {}
                    temp_data['media_data'] = message_data
                    db.set_user_state(phone, 'awaiting_photo', temp_data=temp_data)
            
            # Обрабатываем сообщение
            response_text = process_message(phone, text, has_media=has_media)
            
            # Отправляем ответ
            if response_text:
                whatsapp.send_message(phone, response_text)
                print(f"✅ Ответ отправлен")
        
        return jsonify({"status": "ok"}), 200
    
    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Проверка работоспособности сервера"""
    return jsonify({
        "status": "ok",
        "service": "WhatsApp Weight Bot (Green API)",
        "timestamp": datetime.now().isoformat()
    }), 200


# ==================== ЗАПУСК ====================

if __name__ == '__main__':
    # Создаем необходимые папки
    os.makedirs('uploads/photos', exist_ok=True)
    os.makedirs('data', exist_ok=True)
    
    print("="*60)
    print("🚚 БОТА ДЛЯ УЧЕТА ВЗВЕШИВАНИЯ МАШИН (GREEN API)")
    print("="*60)
    print("✅ База данных инициализирована")
    print("✅ Green API клиент готов")
    print(f"🔑 ID инстанса: {Config.GREEN_API_ID_INSTANCE}")
    print("🌐 Сервер запущен: http://localhost:5000")
    print("\n🔧 Дальнейшие шаги:")
    print("1. Запустите ngrok: ngrok http 5000")
    print("2. Скопируйте https URL из ngrok")
    print("3. Настройте вебхук в Green API на: {YOUR_NGROK_URL}/webhook")
    print("4. Установите GROUP_ID в send_report_to_group()")
    print("5. Напишите боту в WhatsApp: 'меню'")
    print("="*60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)
