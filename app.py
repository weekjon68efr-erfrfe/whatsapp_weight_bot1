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
        
        if not chat_id.endswith('@g.us') and not chat_id.endswith('@c.us'):
            chat_id = f"{chat_id}@c.us"
        
        url = f"{self.base_url}/waInstance{self.id_instance}/sendFileByUrl/{self.api_token}"
        data = {
            "chatId": chat_id,
            "urlFile": url_file,
            "fileName": file_name
        }
        
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
    
    if text_lower == "0" or text_lower == "меню":
        return show_main_menu(phone)
    
    full_name = text.strip()
    
    if len(full_name) < 3:
        return "Пожалуйста, введите полное имя (минимум 3 символа)"
    
    db.set_user_state(phone, 'registration_phone', temp_data={'full_name': full_name})
    
    return f"""
ФИО: {full_name}

Теперь введите ваш личный номер телефона:
Пример: 89123456789
"""


def handle_registration_phone(phone: str, text: str) -> str:
    """Обработка ввода номера телефона при регистрации"""
    text_lower = text.lower().strip()
    
    if text_lower == "0" or text_lower == "меню":
        return show_main_menu(phone)
    
    phone_clean = ''.join(filter(str.isdigit, text))
    
    if len(phone_clean) < 6:
        return "Неверный номер телефона. Введите еще раз (например: 89123456789)"
    
    state = db.get_user_state(phone)
    temp_data = state['temp_data'] if isinstance(state['temp_data'], dict) else {}
    
    full_name = temp_data.get('full_name', '?')
    
    temp_data['personal_phone'] = phone_clean
    db.set_user_state(phone, 'registration_truck', temp_data=temp_data)
    
    return "Введите номер вашей машины:"


def handle_registration_truck(phone: str, text: str) -> str:
    """Обработка ввода номера машины при регистрации"""
    text_lower = text.lower().strip()
    
    if text_lower == "0" or text_lower == "меню":
        return show_main_menu(phone)
    
    truck_number = text.upper().strip()
    
    if len(truck_number) < 3:
        return "Введите правильный номер машины"
    
    state = db.get_user_state(phone)
    temp_data = state['temp_data'] if isinstance(state['temp_data'], dict) else {}
    
    full_name = temp_data.get('full_name', '?')
    personal_phone = temp_data.get('personal_phone', '')
    
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

def process_message(phone: str, text: str, has_media: bool = False, message_data: dict = None) -> str:
    """Главная функция обработки сообщений"""
    
    # Если ожидаем фото и получили медиа
    if has_media and message_data:
        state = db.get_user_state(phone)
        if state and state['state'] == 'awaiting_photo':
            return handle_photo_received(phone, True, message_data)
    
    text_original = text.strip()
    text_lower = text_original.lower()
    
    # Команды верхнего уровня
    if text_lower == "0" or text_lower == "меню":
        return show_main_menu(phone)
    
    if text_lower == "3" or text_lower == "регистрация":
        db.clear_user_state(phone)
        return start_registration(phone)
    
    # Проверяем, зарегистрирован ли водитель
    if not db.is_driver_registered(phone):
        state = db.get_user_state(phone)
        
        if not state:
            db.clear_user_state(phone)
            return start_registration(phone)
        
        if state['state'] == 'registration_name':
            return handle_registration_name(phone, text_original)
        elif state['state'] == 'registration_phone':
            return handle_registration_phone(phone, text_original)
        elif state['state'] == 'registration_truck':
            return handle_registration_truck(phone, text_original)
        
        return start_registration(phone)
    
    # Водитель зарегистрирован - проверяем состояние
    state = db.get_user_state(phone)
    
    # Проверяем процесс переоформления регистрации
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
    
    # Команда "1" - начинаем новый отчет
    if text_lower == "1":
        driver = db.get_driver(phone)
        truck_number = driver.get('truck_number') if driver else None
        
        if truck_number:
            personal_phone = driver.get('personal_phone', '')
            full_name = driver.get('full_name', '?')
            
            db.set_user_state(phone, 'awaiting_client', temp_data={
                'truck_number': truck_number,
                'driver_name': full_name,
                'driver_phone': personal_phone
            })
            return "Введите имя клиента:"
        else:
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
            return handle_photo_received(phone, False, None)
        elif state['state'] == 'awaiting_manual_weight':
            if has_media and message_data:
                return handle_photo_received(phone, True, message_data)
            else:
                return handle_manual_weight_input(phone, text_original)
        elif state['state'] == 'awaiting_confirmation':
            return handle_confirmation(phone, text_original)
    
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
    db.set_user_state(phone, 'awaiting_photo', temp_data=temp_data)
    
    return "Отправьте фото показаний весов:"


def handle_manual_weight_input(phone: str, text: str) -> str:
    """Обработка ручного ввода веса"""
    text_clean = text.strip()
    weight_str = ''.join(c for c in text_clean if c.isdigit() or c == '.')
    
    try:
        weight = float(weight_str)
        
        if weight < 100:
            return "⚠️ Вес слишком мал (нужно не менее 100 кг)\n\nПопробуйте еще раз или отправьте новое фото"
        
        if weight > 150000:
            return "⚠️ Вес слишком велик (максимум 150000 кг)\n\nПопробуйте еще раз или отправьте новое фото"
        
        state = db.get_user_state(phone)
        temp_data = state['temp_data'] if isinstance(state['temp_data'], dict) else {}
        
        current_weight = weight
        temp_data['current_weight'] = current_weight
        temp_data['photo_received'] = True
        temp_data['weight_manual_input'] = True
        
        truck_number = temp_data.get('truck_number', '')
        previous_weight = db.get_last_weight(truck_number)
        temp_data['previous_weight'] = previous_weight
        
        weight_difference = current_weight - previous_weight
        temp_data['weight_difference'] = weight_difference
        
        print(f"✅ Вес введен вручную: {current_weight} кг")
        
        db.set_user_state(phone, 'awaiting_confirmation', temp_data=temp_data)
        
        return f"""✅ Подтверждение отчета

Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}
Телефон: {temp_data.get('driver_phone', '?')}
Машина: {truck_number}
Клиент: {temp_data.get('client_name', '?')}

*Вес ВРУЧНУЮ:* {current_weight:.0f} кг
Вес предыдущий: {previous_weight:.0f} кг
Разница: {weight_difference:+.0f} кг

Напишите "да" для сохранения
Напишите "нет" для отмены
"""
    
    except ValueError:
        return "❌ Не понимаю. Напишите число, например: 15000\n\nИли отправьте новое фото весов"


def handle_photo_received(phone: str, has_media: bool, message_data: dict = None) -> str:
    """Обработка полученного фото с распознаванием веса"""
    
    if not has_media or not message_data:
        return "Пожалуйста, отправьте фото. Просто загрузите изображение в чат."
    
    state = db.get_user_state(phone)
    temp_data = state['temp_data'] if isinstance(state['temp_data'], dict) else {}
    
    print(f"📸 Обработка фото от {phone}")
    
    try:
        # ИСПРАВЛЕНИЕ ОШИБКИ: проверяем что message_data не None и не пустой
        if not isinstance(message_data, dict) or not message_data:
            print(f"❌ message_data некорректны: {message_data}")
            return "❌ Ошибка: некорректные данные фото. Попробуйте еще раз."
        
        # Ищем URL фотографии
        photo_url = None
        
        if 'fileMessageData' in message_data:
            photo_url = message_data.get('fileMessageData', {}).get('downloadUrl')
        elif 'imageMessageData' in message_data:
            photo_url = message_data.get('imageMessageData', {}).get('downloadUrl')
        elif 'photoMessageData' in message_data:
            photo_url = message_data.get('photoMessageData', {}).get('downloadUrl')
        
        if not photo_url:
            print(f"❌ URL фото не найден. Доступные ключи: {message_data.keys()}")
            return "❌ Не удалось получить фото. Попробуйте еще раз."
        
        print(f"📥 Скачивание фото с URL: {photo_url}")
        
        import requests
        response = requests.get(photo_url, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Ошибка при скачивании фото: {response.status_code}")
            return "❌ Ошибка при скачивании фото. Попробуйте еще раз."
        
        # Сохраняем фото
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        photo_path = f'uploads/photos/{phone}_{timestamp}.jpg'
        os.makedirs('uploads/photos', exist_ok=True)
        
        with open(photo_path, 'wb') as f:
            f.write(response.content)
        
        print(f"✅ Фото сохранено: {photo_path}")
        
        # Распознаем вес
        print(f"🔍 Распознавание веса...")
        weight, ocr_message, ocr_details = extract_weight_from_image(photo_path)
        
        if weight is not None:
            print(f"✅ Вес распознан: {weight} кг")
            temp_data['current_weight'] = weight
            temp_data['photo_received'] = True
            temp_data['ocr_details'] = ocr_details
            
            truck_number = temp_data.get('truck_number', '')
            previous_weight = db.get_last_weight(truck_number)
            temp_data['previous_weight'] = previous_weight
            
            weight_difference = weight - previous_weight
            temp_data['weight_difference'] = weight_difference
            temp_data['photo_path'] = photo_path
            
            db.set_user_state(phone, 'awaiting_confirmation', temp_data=temp_data)
            
            return f"""Подтверждение отчета

Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}
Телефон: {temp_data.get('driver_phone', '?')}
Машина: {truck_number}
Клиент: {temp_data.get('client_name', '?')}
Вес новый: {weight:.0f} кг
Вес предыдущий: {previous_weight:.0f} кг
Разница: {weight_difference:+.0f} кг

Напишите "да" для сохранения
Напишите "нет" для отмены
"""
        else:
            print(f"❌ Вес не распознан: {ocr_message}")
            db.set_user_state(phone, 'awaiting_manual_weight', temp_data=temp_data)
            
            return f"""{ocr_message}

💡 *Варианты решения:*

1️⃣ *Отправьте НОВОЕ фото* - более четкое табло весов
2️⃣ *Введите вес вручную* - напишите число (например: 15000)

⚠️ Важно: фото должно показывать четкие цифры на табло весов"""
    
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
    
    if text.lower() in ['нет', 'no', 'н', 'n']:
        db.clear_user_state(phone)
        return "Отчет отменен.\n\nОтправьте 1 для заполнения нового груза или 0 для главного меню"
    
    if text.lower() not in ['да', 'yes', 'д', 'y']:
        return "Пожалуйста, напишите 'да' для сохранения или 'нет' для отмены"
    
    driver = db.get_driver(phone)
    
    weighing_data = {
        'driver_phone': phone,
        'truck_number': temp_data.get('truck_number', ''),
        'driver_name': driver['full_name'] if driver else '',
        'client_name': temp_data.get('client_name', ''),
        'current_weight': temp_data.get('current_weight', 0),
        'station_name': '',
        'photo_received': temp_data.get('photo_received', False),
        'photo_path': temp_data.get('photo_path', '')
    }
    
    result = db.save_weighing(weighing_data)
    
    if result:
        send_report_to_group(phone, temp_data, driver)
        db.clear_user_state(phone)
        
        return """
Отчет сохранен и отправлен!

Отправьте "1" для заполнения нового груза
0 - Главное меню
"""
    else:
        return "Ошибка при сохранении отчета. Попробуйте еще раз."


def send_report_to_group(phone: str, temp_data: dict, driver: dict):
    """Отправить отчет в WhatsApp-группу"""
    truck_number = temp_data.get('truck_number', '?')
    client_name = temp_data.get('client_name', '?')
    driver_phone = temp_data.get('driver_phone', '?')
    driver_name = (driver['full_name'] if driver else '?').upper()
    previous_weight = temp_data.get('previous_weight', 0)
    current_weight = temp_data.get('current_weight', 0)
    weight_diff = temp_data.get('weight_difference', 0)
    
    report = f"""*{driver_name}*  *{driver_phone}*

Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}
Машина: {truck_number}
Клиент: {client_name}

Вес новый: {current_weight:.0f} кг
Вес предыдущий: {previous_weight:.0f} кг
Разница: {weight_diff:+.0f} кг"""
    
    print(f"Отправка отчета в группу:\n{report}")
    
    GROUP_ID = Config.GROUP_ID
    
    if GROUP_ID and GROUP_ID != "":
        print(f"Отправка в группу: {GROUP_ID}")
        whatsapp.send_message(GROUP_ID, report)
    else:
        print(f"GROUP_ID не установлен в .env файле")


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
            
            text = None
            has_media = False
            media_data = None
            
            if "textMessageData" in message_data:
                text = message_data["textMessageData"]["textMessage"]
                print(f"📝 Текстовое сообщение: {text}")
            elif "extendedTextMessageData" in message_data:
                text = message_data["extendedTextMessageData"].get("text", "")
                print(f"📝 Расширенное текстовое сообщение: {text}")
            elif "imageMessageData" in message_data or "photoMessageData" in message_data or "fileMessageData" in message_data:
                has_media = True
                media_data = message_data
                text = "фото"
                print(f"📸 Получено фото/медиа")
            else:
                print(f"⚠️ Неизвестный тип сообщения: {message_data.keys()}")
                return jsonify({"status": "ok"}), 200
            
            chat_id = sender_data.get("chatId", "")
            phone = chat_id.split("@")[0]
            
            if not text:
                return jsonify({"status": "ok"}), 200
            
            print(f"📱 Сообщение от {phone}: {text}")
            
            # Обрабатываем сообщение
            response_text = process_message(phone, text, has_media=has_media, message_data=media_data)
            
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
    os.makedirs('uploads/photos', exist_ok=True)
    os.makedirs('data', exist_ok=True)
    
    print("="*60)
    print("🚚 БОТ ДЛЯ УЧЕТА ВЗВЕШИВАНИЯ МАШИН (GREEN API)")
    print("="*60)
    print("✅ База данных инициализирована")
    print("✅ Green API клиент готов")
    print(f"🔑 ID инстанса: {Config.GREEN_API_ID_INSTANCE}")
    print("🌐 Сервер запущен: http://localhost:5000")
    print("="*60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)
